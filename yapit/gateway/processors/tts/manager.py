import asyncio
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from yapit.contracts import SynthesisMode, get_queue_name
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.processors.tts.base import BaseTTSProcessor


@dataclass
class SynthesisRoute:
    model: str
    mode: SynthesisMode
    backend: BaseTTSProcessor
    overflow: BaseTTSProcessor | None = None


class TTSProcessorManager:
    def __init__(self, settings: Settings, redis: Redis, cache: Cache) -> None:
        self._settings = settings
        self._redis = redis
        self._cache = cache
        self._tasks: list[asyncio.Task] = []
        self._routes: dict[tuple[str, SynthesisMode], SynthesisRoute] = {}

    def _load_processor_class(self, class_path: str) -> type[BaseTTSProcessor]:
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def _create_processor(self, processor_class_path: str, model: str, config: dict[str, Any]) -> BaseTTSProcessor:
        processor_class = self._load_processor_class(processor_class_path)
        return processor_class(
            redis=self._redis,
            cache=self._cache,
            settings=self._settings,
            model=model,
            **config,
        )

    def _load_routes(self, config_path: str) -> None:
        with Path(config_path).open() as f:
            route_configs = json.load(f)

        for rc in route_configs:
            model = rc["model"]
            mode = rc["mode"]

            backend_config = rc["backend"].copy()
            processor_path = backend_config.pop("processor")
            backend = self._create_processor(processor_path, model, backend_config)

            overflow = None
            if "overflow" in rc:
                overflow_config = rc["overflow"].copy()
                overflow_path = overflow_config.pop("processor")
                overflow = self._create_processor(overflow_path, model, overflow_config)

            self._routes[(model, mode)] = SynthesisRoute(
                model=model,
                mode=mode,
                backend=backend,
                overflow=overflow,
            )

        logger.info(f"Loaded {len(self._routes)} synthesis route(s)")

    async def start(self, config_path: str) -> None:
        self._load_routes(config_path)

        for route in self._routes.values():
            self._tasks.append(asyncio.create_task(route.backend.run()))

        logger.info(f"Started {len(self._tasks)} TTS processor(s)")

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._routes.clear()
        self._tasks.clear()
        logger.info("All processors stopped")

    def get_route(self, model: str, mode: SynthesisMode) -> SynthesisRoute | None:
        return self._routes.get((model, mode))

    async def get_queue_depth(self, model: str) -> int:
        return await self._redis.llen(get_queue_name(model))
