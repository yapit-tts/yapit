import json
import os

from yapit.contracts.redis_keys import TTS_AUDIO, TTS_INFLIGHT
from yapit.contracts.synthesis import SynthesisJob
from yapit.contracts.worker_id import WorkerId
from yapit.workers.redis_job_processor import RedisJobProcessor
from yapit.workers.synth_adapter import SynthAdapter

WORKER_ID = os.getenv("WORKER_ID")


class LocalProcessor(RedisJobProcessor):
    """Process synthesis jobs locally using a SynthAdapter."""

    def __init__(self, adapter: SynthAdapter):
        if not WORKER_ID:
            raise ValueError("WORKER_ID environment variable must be set")

        worker_id = WorkerId.from_string(WORKER_ID)
        super().__init__(worker_id.to_queue_name())
        self.adapter = adapter

    async def process_job(self, job: SynthesisJob) -> None:
        """Process a synthesis job locally."""
        # Synthesize audio
        audio_bytes = await self.adapter.synthesize(job.text, voice=job.voice_slug, speed=job.speed)
        dur_ms = self.adapter.calculate_duration_ms(audio_bytes)

        # Store result in Redis
        r = await self._get_redis()
        await r.set(TTS_AUDIO.format(hash=job.variant_hash), audio_bytes, ex=3600)  # todo shorter expiry?
        await r.publish(job.done_channel, json.dumps({"duration_ms": dur_ms}))
        await r.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

    async def run(self) -> None:
        """Initialize adapter and start processing."""
        await self.adapter.initialize()
        await super().run()
