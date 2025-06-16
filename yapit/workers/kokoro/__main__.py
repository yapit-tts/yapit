import asyncio

from yapit.workers.kokoro.worker import KokoroAdapter
from yapit.workers.local_runner import LocalWorkerRunner

if __name__ == "__main__":
    adapter = KokoroAdapter()
    runner = LocalWorkerRunner(adapter)
    asyncio.run(runner.run())
