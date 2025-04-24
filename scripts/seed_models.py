import asyncio

from gateway.db import SessionLocal
from gateway.domain.models import Model, Voice


async def main() -> None:
    async with SessionLocal() as db:
        if await db.get(Model, "kokoro"):
            print("DB already seeded")
            return
        m = Model(id="kokoro", description="Kokoro TTS", price_sec=0.0)
        v = Voice(id="af_heart", model_id="kokoro", name="af_heart", lang="af", gender="female")
        db.add_all([m, v])
        await db.commit()


asyncio.run(main())
