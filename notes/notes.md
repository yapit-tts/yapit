
Kokoro silently tries to auto‑install spaCy if en_core_web_sm is missing, fails (no root), then retries on every call ⇒ nothing ever streams. Pre‑install the model in the CPU image just like we did for GPU.

torch OMP_NUM_THREADS: If you see CPU utilization ≫ #cores, reduce threads; if < #cores, you can raise them.
Too high → context‑switch overhead.
Rule of thumb: cores / 2

Separate copy command for requirements.txt in Dockerfile to avoid cache busting -> can edit pythong file without needing to re-install all dependencies.

Generate first alembic revision:
```
alembic init migrations
alembic revision --autogenerate -m "initial"
```

