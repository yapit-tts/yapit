import importlib
import json
import logging
from abc import ABC
from pathlib import Path
from typing import Type, TypedDict, Unpack

from yapit.gateway.config import Settings


class ProcessorConfig(TypedDict):
    """Configuration for a document processor."""

    slug: str
    # plus optional fields for processor-specific settings


class Processor(ABC):
    def __init__(self, settings: Settings, **kwargs: Unpack[ProcessorConfig]) -> None:
        self._settings = settings
        self._slug = kwargs["slug"]


class ProcessorManager[T: Processor]:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._processors: dict[str, T] = {}

    def _load_processors(self, config_path: str) -> None:
        """Load processor configuration from JSON file and create processor instances."""
        with Path(config_path).open() as f:
            processor_configs = json.load(f)
        if not processor_configs:
            logging.warning(f"No processors configured in {config_path}. Some functionality will not be available.")
            return
        self._processors = {
            config["slug"]: self._create_processor(config.pop("processor"), config) for config in processor_configs
        }
        logging.info(
            f"Loaded {len(self._processors)} processor(s) with configs:\n{json.dumps(processor_configs, indent=2)}"
        )

    def _create_processor(self, processor_class_path: str, config: ProcessorConfig) -> T:
        """Create a processor instance from configuration."""
        processor_class = self._load_processor_class(processor_class_path)
        processor = processor_class(settings=self._settings, **config)
        return processor

    @staticmethod
    def _load_processor_class(class_path: str) -> Type[T]:
        """Dynamically load a processor class from its module path.

        Args:
            class_path: Full path to the class (e.g., "yapit.gateway.processors.document.mistral.MistralOCRProcessor")

        Returns:
            The loaded class
        """
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def get_processor(self, slug: str) -> T | None:
        return self._processors.get(slug)
