import asyncio
import logging

from redis.asyncio import Redis

from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.processors.base import ProcessorConfig, ProcessorManager
from yapit.gateway.processors.tts.base import BaseTTSProcessor

log = logging.getLogger("processor_manager")


class TTSProcessorManager(ProcessorManager[BaseTTSProcessor]):
    def __init__(self, settings: Settings, redis: Redis, cache: Cache) -> None:
        super().__init__(settings=settings)
        self._redis = redis
        self._cache = cache
        self._tasks: list[asyncio.Task] = []

    def _create_processor(self, config: ProcessorConfig) -> BaseTTSProcessor:
        """Create a processor instance from configuration."""
        config = config.copy()
        processor_class = self._load_processor_class(config.pop("processor"))
        return processor_class(redis=self._redis, cache=self._cache, settings=self._settings, **config)

    async def start(self, config_path: str) -> None:
        """Load endpoint configuration and start all processors."""
        self._load_processors(config_path)
        self._tasks = [asyncio.create_task(processor.run()) for processor in self._processors.values()]
        log.info(f"Started {len(self._tasks)} TTS processor(s)")

    async def stop(self) -> None:
        """Stop all running processors."""
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._processors.clear()
        self._tasks.clear()
        log.info("All processors stopped")
