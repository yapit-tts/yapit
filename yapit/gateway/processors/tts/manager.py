import asyncio
import importlib
import json
import logging
import pprint
from pathlib import Path
from typing import TypedDict

from redis.asyncio import Redis

from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.processors.tts.base import BaseProcessor

log = logging.getLogger("processor_manager")


class TTSProcessorConfig(TypedDict):
    model_slug: str
    processor: str
    # plus optional fields for processor-specific settings


class ProcessorManager:
    """Manages multiple processor instances based on endpoint configuration."""

    def __init__(self, redis: Redis, cache: Cache, settings: Settings):
        self._redis = redis
        self._cache = cache
        self._settings = settings
        self._processors: list[BaseProcessor] = []
        self._tasks: list[asyncio.Task] = []

    def _load_processor_class(self, class_path: str) -> type[BaseProcessor]:
        """Dynamically load a processor class from its module path."""
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        processor_class = getattr(module, class_name)

        if not issubclass(processor_class, BaseProcessor):
            raise TypeError(f"{class_path} is not a BaseProcessor subclass")

        return processor_class

    def _create_processor(self, config: TTSProcessorConfig) -> BaseProcessor:
        """Create a processor instance from configuration."""
        config = config.copy()
        processor_class = self._load_processor_class(class_path=config.pop("processor"))
        return processor_class(redis=self._redis, cache=self._cache, settings=self._settings, **config)

    async def start_from_config(self, config_path: str) -> None:
        """Load endpoint configuration and start all processors."""
        if not config_path:
            log.warning("No endpoints file configured. TTS functionality will not be available.")
            return
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Endpoints configuration file not found: {config_path}")
        with path.open() as f:
            configs = json.load(f)
        if not configs:
            log.warning("No endpoints configured in %s TTS functionality will not be available.", config_path)
            return
        self._processors = [self._create_processor(config) for config in configs]
        self._tasks = [asyncio.create_task(processor.run()) for processor in self._processors]
        log.info(f"Started {len(self._processors)} processor(s) with configs:\n{pprint.pformat(configs)}")

    async def stop(self) -> None:
        """Stop all running processors."""
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._processors.clear()
        self._tasks.clear()
        log.info("All processors stopped")
