import asyncio

from yapit.workers.adapters.kokoro import KokoroAdapter
from yapit.workers.processors.local import LocalProcessor

if __name__ == "__main__":
    adapter = KokoroAdapter()
    processor = LocalProcessor(adapter)
    asyncio.run(processor.run())
