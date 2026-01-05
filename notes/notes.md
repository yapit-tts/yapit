
- Runpod has a bunch of quirks if max workers is 1: https://www.answeroverflow.com/m/1186443848050802758

- Kokoro silently tries to auto‑install spaCy if en_core_web_sm is missing, fails (no root), then retries on every call ⇒ nothing ever streams. Pre‑install the model in the CPU image just like we did for GPU.

- Separate copy command for requirements.txt in Dockerfile to avoid cache busting -> can edit python file without needing to re-install all dependencies.
- Put COPY commands for the source / frequently changed files as late as possible in the Dockerfile to avoid cache busting.

- Generate first alembic revision:
```
alembic init migrations
alembic revision --autogenerate -m "initial"
```

