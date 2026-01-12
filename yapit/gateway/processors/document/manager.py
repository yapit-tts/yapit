import importlib
import json
from pathlib import Path

from loguru import logger

from yapit.gateway.config import Settings
from yapit.gateway.processors.document.base import BaseDocumentProcessor


class DocumentProcessorManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._text_processor: BaseDocumentProcessor | None = None
        self._extraction_processor: BaseDocumentProcessor | None = None

    def load_processors(self, config_path: str) -> None:
        with Path(config_path).open() as f:
            config = json.load(f)

        if "text" in config:
            text_config = config["text"].copy()
            processor_class = text_config.pop("processor")
            self._text_processor = self._create_processor(processor_class, text_config)
            logger.info(f"Loaded text processor: {text_config.get('slug')}")

        if "extraction" in config:
            extraction_config = config["extraction"].copy()
            processor_class = extraction_config.pop("processor")
            self._extraction_processor = self._create_processor(processor_class, extraction_config)
            logger.info(f"Loaded extraction processor: {extraction_config.get('slug')}")

    def _create_processor(self, processor_class_path: str, config: dict) -> BaseDocumentProcessor:
        module_path, class_name = processor_class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        processor_class = getattr(module, class_name)
        return processor_class(settings=self._settings, **config)

    def get_text_processor(self) -> BaseDocumentProcessor | None:
        return self._text_processor

    def get_extraction_processor(self) -> BaseDocumentProcessor | None:
        return self._extraction_processor
