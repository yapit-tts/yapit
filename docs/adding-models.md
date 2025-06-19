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

### 2. Create Worker Entry Point

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
  yourmodel-cpu:
    init: true
    build:
      context: .
      dockerfile: yapit/workers/yourmodel/Dockerfile
    environment:
      ADAPTER_CLASS: yapit.workers.adapters.yourmodel.YourModelAdapter
      DEVICE: cpu  # Required if your adapter uses it
    ports:
      - "8001:8000"  # Use different port if running multiple workers
    restart: unless-stopped
```

### 6. Configure Endpoint

Add to `endpoints.json`:

```json
{
  "model": "yourmodel-cpu",
  "adapter": "yapit.workers.adapters.yourmodel.YourModelAdapter",
  "processor": "yapit.gateway.processors.local.LocalProcessor",
  "worker_url": "http://yourmodel-cpu:8000",
  "max_parallel": 2
}
```

### 7. Add Database Entry

The model slug in endpoints.json must match a database entry:

```sql
INSERT INTO tts_model (slug, name, provider) 
VALUES ('yourmodel-cpu', 'YourModel CPU', 'yourprovider');
```

### 8. Run

```bash
# Start gateway and your worker
docker compose -f docker-compose.yml -f docker-compose.yourmodel.yml up
```

## RunPod Deployment

### 1. Update Dependencies for RunPod

Add runpod to your `pyproject.toml` dependencies:

```toml
dependencies = [
    "pydantic~=2.11.3",
    "fastapi[standard]~=0.115.12",
    "numpy~=2.3.0",
    "runpod~=1.7.12",  # Add this
    # Your model's dependencies here
]
```

### 2. Build and Push Image

```bash
docker build -f yapit/workers/yourmodel/Dockerfile -t your-registry/yapit-yourmodel:latest .
docker push your-registry/yapit-yourmodel:latest
```

### 3. Create RunPod Endpoint

1. Go to [RunPod Serverless](https://www.runpod.io/console/serverless)
2. Click "New Endpoint"
3. Configure:
   - Container Image: `your-registry/yapit-yourmodel:latest`
   - Environment Variables:
     - `ADAPTER_CLASS`: `yapit.workers.adapters.yourmodel.YourModelAdapter`
     - `DEVICE`: `cuda` (if your adapter needs it)
   - GPU Type: Select based on needs
   - Workers: Min 0, Max as needed

### 4. Configure RunPod Endpoint

Add to `endpoints.json`:

```json
{
  "model": "yourmodel-runpod",
  "adapter": "yapit.workers.adapters.yourmodel.YourModelAdapter",
  "processor": "yapit.gateway.processors.runpod.RunPodProcessor",
  "runpod_endpoint_id": "your-endpoint-id-from-runpod"
}
```

Add database entry:

```sql
INSERT INTO tts_model (slug, name, provider) 
VALUES ('yourmodel-runpod', 'YourModel RunPod', 'yourprovider');
```

### 5. Set RunPod API Key

In `.env` or `.env.local`:

```bash
RUNPOD_API_KEY=your-runpod-api-key
```

## Notes

- Model weights should be downloaded at Docker build time, not runtime
- Audio must be returned as raw PCM bytes (int16)
- Implement `calculate_duration_ms()` based on your audio format (sample rate, channels, bit depth)
- Each model variant (cpu/gpu/runpod) needs its own database entry
- Worker URLs in endpoints.json use Docker service names for local workers