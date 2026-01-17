import asyncio
import os

from yapit.workers.adapters.higgs_audio_v2_native import HiggsAudioV2NativeAdapter
from yapit.workers.queue_worker import run_worker

if __name__ == "__main__":
    redis_url = os.environ["REDIS_URL"]
    worker_id = os.environ["WORKER_ID"]

    adapter = HiggsAudioV2NativeAdapter()
    asyncio.run(run_worker(redis_url, "higgs", adapter, worker_id))
