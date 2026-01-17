import asyncio
import os

from yapit.workers.adapters.kokoro import KokoroAdapter
from yapit.workers.queue_worker import run_worker

if __name__ == "__main__":
    redis_url = os.environ["REDIS_URL"]
    worker_id = os.environ["WORKER_ID"]

    adapter = KokoroAdapter()
    asyncio.run(run_worker(redis_url, "kokoro", adapter, worker_id))
