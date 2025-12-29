import importlib
import json
import logging
from pathlib import Path

from yapit.gateway.config import Settings
from yapit.gateway.processors.document.base import BaseDocumentProcessor


class DocumentProcessorManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._processors: dict[str, BaseDocumentProcessor] = {}

    def load_processors(self, config_path: str) -> None:
        with Path(config_path).open() as f:
            processor_configs = json.load(f)
        if not processor_configs:
            logging.warning(f"No processors configured in {config_path}. Some functionality will not be available.")
            return
        self._processors = {
            config["slug"]: self._create_processor(config.pop("processor"), config) for config in processor_configs
        }
        logging.info(f"Loaded {len(self._processors)} document processor(s)")

    def _create_processor(self, processor_class_path: str, config: dict) -> BaseDocumentProcessor:
        module_path, class_name = processor_class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        processor_class = getattr(module, class_name)
        return processor_class(settings=self._settings, **config)

    def get_processor(self, slug: str) -> BaseDocumentProcessor | None:
        return self._processors.get(slug)
