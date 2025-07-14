import importlib
import json
import logging
from pathlib import Path
from typing import Type, TypedDict

from yapit.gateway import Settings


class ProcessorConfig(TypedDict):
    """Configuration for a document processor."""

    slug: str
    processor: str
    # plus optional fields for processor-specific settings


class ProcessorManager[Processor]:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._processors: list[Processor] = []

    def _load_processors(self, config_path: str) -> None:
        """Load processor configuration from JSON file and create processor instances."""
        with Path(config_path).open() as f:
            processor_configs = json.load(f)
        if not processor_configs:
            logging.warning(f"No processors configured in {config_path}. Some functionality will not be available.")
            return
        self._processors = [self._create_processor(config) for config in processor_configs]
        logging.info(
            f"Loaded {len(self._processors)} processor(s) with configs:\n{json.dumps(processor_configs, indent=2)}"
        )

    def _create_processor(self, config: ProcessorConfig) -> Processor:
        """Create a processor instance from configuration."""
        config = config.copy()  # because TypedDict is immutable and processor is a required field
        processor_class = self._load_processor_class(config.pop("processor"))
        processor = processor_class(settings=self._settings, **config)
        return processor

    @staticmethod
    def _load_processor_class(class_path: str) -> Type[Processor]:
        """Dynamically load a processor class from its module path.

        Args:
            class_path: Full path to the class (e.g., "yapit.gateway.processors.document.mistral.MistralOCRProcessor")

        Returns:
            The loaded class
        """
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
