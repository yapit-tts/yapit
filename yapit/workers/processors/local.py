from yapit.contracts import SynthesisJob
from yapit.workers.adapters.base import SynthAdapter
from yapit.workers.processors.base import JobResult, RedisJobProcessor


class LocalProcessor(RedisJobProcessor):
    """Process synthesis jobs locally using a SynthAdapter."""

    def __init__(self, adapter: SynthAdapter):
        super().__init__()
        self._adapter = adapter

    async def initialize(self) -> None:
        await self._adapter.initialize()

    async def process(self, job: SynthesisJob) -> JobResult:
        audio_bytes = await self._adapter.synthesize(job.text, voice=job.voice_slug, speed=job.speed)
        dur_ms = self._adapter.calculate_duration_ms(audio_bytes)
        return JobResult(audio=audio_bytes, duration_ms=dur_ms)
