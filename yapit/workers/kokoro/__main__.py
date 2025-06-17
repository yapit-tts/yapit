import asyncio

from yapit.workers.kokoro.worker import KokoroAdapter
from yapit.workers.local_runner import LocalProcessor

if __name__ == "__main__":
    adapter = KokoroAdapter()
    processor = LocalProcessor(adapter)
    asyncio.run(processor.run())
