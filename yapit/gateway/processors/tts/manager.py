import asyncio
import importlib
import json
import logging
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.processors.tts.base import BaseProcessor

log = logging.getLogger("processor_manager")


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

    def _create_processor(self, config: dict[str, Any]) -> BaseProcessor:
        """Create a processor instance from configuration."""
        config = config.copy()
        model_slug = config.pop("model")
        processor_class_path = config.pop("processor")
        config.pop("adapter")

        processor_class = self._load_processor_class(processor_class_path)

        config.update(dict(redis=self._redis, cache=self._cache, settings=self._settings))
        return processor_class(model_slug, **config)

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

        for config in configs:
            processor = self._create_processor(config)
            self._processors.append(processor)
            log.info(f"Created processor for model: {config['model']}")

        self._tasks = [asyncio.create_task(processor.run()) for processor in self._processors]
        log.info(f"Started {len(self._processors)} processor(s)")

    async def stop(self) -> None:
        """Stop all running processors."""
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._processors.clear()
        self._tasks.clear()
        log.info("All processors stopped")
