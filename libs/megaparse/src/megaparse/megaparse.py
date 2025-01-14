import logging
import warnings
from pathlib import Path
from typing import IO, BinaryIO, List

from megaparse_sdk.schema.extensions import FileExtension
from megaparse_sdk.schema.parser_config import StrategyEnum

from megaparse.configs.auto import DeviceEnum, MegaParseConfig
from megaparse.exceptions.base import ParsingException
from megaparse.formatter.base import BaseFormatter
from megaparse.parser.base import BaseParser
from megaparse.parser.doctr_parser import DoctrParser
from megaparse.parser.strategy import StrategyHandler
from megaparse.parser.unstructured_parser import UnstructuredParser

logger = logging.getLogger("megaparse")


class MegaParse:
    config = MegaParseConfig()

    def __init__(
        self,
        parser: BaseParser | None = None,
        ocr_parser: BaseParser | None = None,
        formatters: List[BaseFormatter] | None = None,
        strategy: StrategyEnum = StrategyEnum.AUTO,
    ) -> None:
        if not parser:
            parser = UnstructuredParser(strategy=StrategyEnum.FAST)
        if not ocr_parser:
            ocr_parser = DoctrParser(
                text_det_config=self.config.text_det_config,
                text_reco_config=self.config.text_reco_config,
                device=self.config.device,
            )

        self.strategy = strategy
        self.parser = parser
        self.formatters = formatters
        self.ocr_parser = ocr_parser

        self.strategy_handler = StrategyHandler(
            text_det_config=self.config.text_det_config,
            auto_config=self.config.auto_parse_config,
            device=self.config.device,
        )

    def validate_input(
        self,
        file_path: Path | str | None = None,
        file: IO[bytes] | None = None,
        file_extension: str | FileExtension | None = None,
    ) -> FileExtension:
        if not (file_path or file):
            raise ValueError("Either file_path or file should be provided")

        if file_path and file:
            raise ValueError("Only one of file_path or file should be provided")

        if file_path and file is None:
            if isinstance(file_path, str):
                file_path = Path(file_path)
            file_extension = file_path.suffix
        elif file and file_path is None:
            if not file_extension:
                raise ValueError(
                    "file_extension should be provided when given file argument"
                )
            file.seek(0)
        else:
            raise ValueError("Either provider a file_path or file")

        if isinstance(file_extension, str):
            try:
                file_extension = FileExtension(file_extension)
            except ValueError:
                raise ValueError(f"Unsupported file extension: {file_extension}")
        return file_extension

    async def aload(
        self,
        file_path: Path | str | None = None,
        file: BinaryIO | None = None,
        file_extension: str | FileExtension = "",
    ) -> str:
        file_extension = self.validate_input(
            file=file, file_path=file_path, file_extension=file_extension
        )
        try:
            parser = self._select_parser(file_path, file, file_extension)
            logger.info(f"Parsing using {parser.__class__.__name__} parser.")
            parsed_document = await parser.aconvert(
                file_path=file_path, file=file, file_extension=file_extension
            )
            parsed_document.file_name = str(file_path) if file_path else None

            if self.formatters:
                for formatter in self.formatters:
                    if isinstance(parsed_document, str):
                        warnings.warn(
                            f"The last step returned a string, the {formatter.__class__} and following will not be applied",
                            stacklevel=2,
                        )
                        break
                    parsed_document = await formatter.aformat(parsed_document)

            # @chloe FIXME: format_checker needs unstructured Elements as input which is to change
            # if self.format_checker:
            #     parsed_document: str = self.format_checker.check(parsed_document)
            if not isinstance(parsed_document, str):
                return str(parsed_document)
            return parsed_document
        except Exception as e:
            raise ParsingException(
                f"Error while parsing file {file_path or file}, file_extension: {file_extension}: {e}"
            )

    def load(
        self,
        file_path: Path | str | None = None,
        file: BinaryIO | None = None,
        file_extension: str | FileExtension = "",
    ) -> str:
        file_extension = self.validate_input(
            file=file, file_path=file_path, file_extension=file_extension
        )
        try:
            parser = self._select_parser(file_path, file, file_extension)
            logger.info(f"Parsing using {parser.__class__.__name__} parser.")
            parsed_document = parser.convert(
                file_path=file_path, file=file, file_extension=file_extension
            )
            parsed_document.file_name = str(file_path) if file_path else None

            if self.formatters:
                for formatter in self.formatters:
                    if isinstance(parsed_document, str):
                        warnings.warn(
                            f"The last step returned a string, the {formatter.__class__} and following will not be applied",
                            stacklevel=2,
                        )
                        break
                    parsed_document = formatter.format(parsed_document)

            # @chloe FIXME: format_checker needs unstructured Elements as input which is to change
            # if self.format_checker:
            #     parsed_document: str = self.format_checker.check(parsed_document)
            if not isinstance(parsed_document, str):
                return str(parsed_document)
            return parsed_document
        except Exception as e:
            raise ParsingException(
                f"Error while parsing file {file_path or file}, file_extension: {file_extension}: {e}"
            )

    def _select_parser(
        self,
        file_path: Path | str | None = None,
        file: BinaryIO | None = None,
        file_extension: str | FileExtension = "",
    ) -> BaseParser:
        local_strategy = None
        if self.strategy != StrategyEnum.AUTO or file_extension != FileExtension.PDF:
            return self.parser
        if file:
            local_strategy = self.strategy_handler.determine_strategy(
                file=file,  # type: ignore #FIXME: Careful here on removing BinaryIO (not handled by onnxtr)
            )
        if file_path:
            local_strategy = self.strategy_handler.determine_strategy(file=file_path)

        if local_strategy == StrategyEnum.HI_RES:
            return self.ocr_parser
        return self.parser
