# Adding Models to Yapit

## Architecture Overview

Models in yapit are deployed as HTTP services that processors call:
- **Adapter**: Implements TTS synthesis logic
- **Worker**: HTTP server running the adapter
- **Processor**: Gateway-side component that forwards jobs to workers

## Adding a New Model

### 1. Create the Adapter

Create `yapit/workers/adapters/yourmodel.py`:

```python
import numpy as np
from yapit.workers.adapters.base import SynthAdapter

class YourModelAdapter(SynthAdapter):
    async def initialize(self) -> None:
        """Load model weights here."""
        # self.model = load_your_model()
        pass
    
    async def synthesize(self, text: str, *, voice: str, speed: float) -> bytes:
        """Convert text to PCM audio bytes (16-bit mono/stereo)."""
        # audio = self.model.synthesize(text, voice=voice, speed=speed)
        # Convert to int16 PCM:
        # return (audio * 32767).astype(np.int16).tobytes()
        pass
    
    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        """Calculate duration from PCM bytes."""
        # Example for 24kHz mono 16-bit:
        # return int(len(audio_bytes) / (24_000 * 1 * 2) * 1000)
        pass
```

### 2. Create Worker Entry Point (Skip if only using RunPod -- see below)

Create `yapit/workers/yourmodel/__main__.py`:

```python
import uvicorn
from yapit.workers.handlers.local import create_app

if __name__ == "__main__":
    app = create_app("yapit.workers.adapters.yourmodel.YourModelAdapter")
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### 3. Create Worker Dependencies

Create `yapit/workers/yourmodel/pyproject.toml`:

```toml
[project]
name = "yapit-yourmodel"
version = "0.1.0"
requires-python = ">=3.11,<=3.12"
dependencies = [
    "pydantic~=2.11.3",
    "fastapi[standard]~=0.115.12",
    "numpy~=2.3.0",
    # Your model's dependencies here
]
```

### 4. Create Dockerfile

Create `yapit/workers/yourmodel/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY yapit/workers/yourmodel/pyproject.toml ./
RUN pip install uv --no-cache-dir && \
    uv pip install . --no-cache-dir --system

# Copy code
COPY yapit/ /app/yapit

# Download model weights at build time
# RUN python -c "import your_model; your_model.download_weights()"

ENV PYTHONUNBUFFERED=1
ENV ADAPTER_CLASS=yapit.workers.adapters.yourmodel.YourModelAdapter
CMD ["python", "-m", "yapit.workers.yourmodel"]
```

### 5. Create Docker Compose Service

Create `docker-compose.yourmodel.yml`:

```yaml
services:
  yourmodel:
    init: true
    build:
      context: .
      dockerfile: yapit/workers/yourmodel/Dockerfile
    environment:
      ADAPTER_CLASS: yapit.workers.adapters.yourmodel.YourModelAdapter
      # DEVICE: cpu/cuda if needed
    ports:
      - "8001:8000"  # Use different port if running multiple workers
    restart: unless-stopped
```

### 6. Configure Endpoint

Add to `tts_processors.json`:

```json
{
  "slug": "yourmodel",
  "processor": "yapit.gateway.processors.tts.local.LocalProcessor",
  "worker_url": "http://yourmodel:8000",
  "max_parallel": 2
}
```

`slug` should match the slug for the model in the database.

### 7. Add Database Entry

Create a new model in the frontend with the right slug `yourmodel`.

TODO: For now, see `yapit/gateway/dev_seed.py`.

## RunPod Deployment

### 1. Update Dependencies for RunPod

Add `runpod` to your worker's `pyproject.toml` dependencies.

### 2. Create RunPod Endpoint

1. Go to [RunPod Serverless](https://www.runpod.io/console/serverless)
2. Click "New Endpoint"
3. Configure:
   - Select Dockerfile via GitHub integration or from docker registry
   - Public Environment Variables if needed for the adapter.
   - Docker Configuration:
     - Container Start Command (overwrite CMD): `python -m yapit.workers.handlers.runpod` 
     - Or rather use `python3 -m yapit.workers.handlers.runpod` unless you use a python base image.
     - Don't forget to set this because runpod removed the ability to EDIT the CMD overwrite after the endpoint is created for whatever reason.

### 4. Configure Runpod Endpoint

Add to `tts_processors.json`:

```json
{
  "slug": "yourmodel",
  "processor": "yapit.gateway.processors.tts.runpod.RunpodProcessor",
  "runpod_endpoint_id": "your-endpoint-id-from-runpod"
}
```

### 5. Set Runpod API Key

In `.env.local` for development, or `.env.prod` for production, add:
```
RUNPOD_API_KEY=your-runpod-api-key
```

## Notes

- To simoultaneously serve the same model locally and on RunPod (or different runpod endpoints, different providers, ...), create  
  separate database entries, and corresponding entries in `tts_processors.json`.
- Worker URLs in tts_processors.json use Docker service names for local workers
