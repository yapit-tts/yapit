# Adding Models to Yapit

This guide explains how to add new TTS models to yapit, both for local deployment and RunPod.

## Prerequisites

1. Create a database entry for your model in the `TTSModel` table with a unique slug
2. Implement a `SynthAdapter` for your model

## Adding a Local Model

### 1. Create the Adapter

Create `yapit/workers/yourmodel/worker.py`:

```python
from yapit.workers.synth_adapter import SynthAdapter

class YourModelAdapter(SynthAdapter):
    sample_rate = 24_000  # Your model's sample rate
    channels = 1          # Mono/stereo
    sample_width = 2      # Bytes per sample (2 for int16)
    native_codec = "pcm"  # Output format
    
    async def initialize(self) -> None:
        # Load your model here
        pass
    
    async def synthesize(self, text: str, *, voice: str, speed: float) -> bytes:
        # Synthesize and return PCM audio bytes
        pass
```

### 2. Create Entry Point

Create `yapit/workers/yourmodel/__main__.py`:

```python
import asyncio
from yapit.workers.yourmodel.worker import YourModelAdapter
from yapit.workers.local_runner import LocalProcessor

if __name__ == "__main__":
    adapter = YourModelAdapter()
    processor = LocalProcessor(adapter)
    asyncio.run(processor.run())
```

### 3. Create Dockerfile

Create `yapit/workers/yourmodel/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml README.md ./
RUN pip install uv --no-cache-dir && \
    uv pip install ".[yourmodel]" --no-cache-dir --system

# Copy worker code
COPY yapit/ /app/yapit

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "yapit.workers.yourmodel"]
```

### 4. Create Docker Compose File

Create `docker-compose.yourmodel.yml`:

```yaml
services:
  yourmodel:
    init: true
    build:
      context: .
      dockerfile: yapit/workers/yourmodel/Dockerfile
    environment:
      WORKER_ID: local/yourmodel/cpu  # Format: deployment/model/device
      DEVICE: cpu                     # or cuda for GPU
      WORKER_CONCURRENCY: 2           # Number of parallel jobs
    depends_on:
      - redis
    restart: unless-stopped
```

### 5. Run Your Model

```bash
# Start with your model
docker-compose -f docker-compose.yml -f docker-compose.yourmodel.yml up
```

## Adding a RunPod Model

### 1. Update RunPod Handler

Add your model to the adapter map in `yapit/workers/runpod_handler.py`:

```python
adapter_map = {
    "kokoro": "yapit.workers.kokoro.worker.KokoroAdapter",
    "yourmodel": "yapit.workers.yourmodel.worker.YourModelAdapter",  # Add this
}
# The model name is extracted from WORKER_ID environment variable
```

### 2. Build and Push Docker Image

```bash
# Build image with RunPod support
docker build -f yapit/workers/yourmodel/Dockerfile -t your-registry/yapit-yourmodel:latest .

# Push to registry
docker push your-registry/yapit-yourmodel:latest
```

### 3. Create RunPod Endpoint

1. Go to [RunPod Serverless](https://www.runpod.io/console/serverless)
2. Click "New Endpoint"
3. Select your Docker image
4. Set environment variable: `MODEL_TYPE=yourmodel`
5. Configure GPU and scaling settings
6. Deploy and note the endpoint ID

### 4. Configure RunPod Bridge

Set environment variables for the bridge service:

```bash
# In .env.prod or docker-compose.runpod.yml
RUNPOD_API_KEY=your-api-key
RUNPOD_ENDPOINT_YOURMODEL=endpoint-id-from-step-3
```

### 5. Create Database Entry

Create a TTSModel entry with slug `yourmodel-runpod`.

### 6. Run with RunPod

```bash
# Start gateway with RunPod bridge
docker-compose -f docker-compose.yml -f docker-compose.runpod.yml up
```

## Environment Variables Reference

### Local Workers

| Variable | Description | Example |
|----------|-------------|---------|
| `WORKER_ID` | Worker identifier | `local/kokoro/cpu` |
| `DEVICE` | Device to use | `cpu` or `cuda` |
| `WORKER_CONCURRENCY` | Parallel jobs | `2` |
| `REDIS_URL` | Redis connection | `redis://redis:6379/0` (default) |

### RunPod Bridge

| Variable | Description | Example |
|----------|-------------|---------|
| `RUNPOD_API_KEY` | RunPod API key | `rp_xxx` |
| `RUNPOD_ENDPOINT_<MODEL>` | Endpoint ID for model | `RUNPOD_ENDPOINT_KOKORO=abc123` |

## How It Works

1. **Queue Naming**: Worker ID determines Redis queue
   - `local/kokoro/cpu` → `yapit:queue:local/kokoro/cpu`
   - `runpod/kokoro/gpu` → `yapit:queue:runpod/kokoro/gpu`

2. **Local Workers**: Listen to their specific queue based on `WORKER_ID`

3. **RunPod Processor**: 
   - Each processor monitors a specific queue for its model
   - Maps model names to endpoint IDs via environment variables
   - Forwards jobs to RunPod and returns results

## Best Practices

1. Use consistent worker ID format: `deployment/model/device`
   - `local/kokoro/cpu`, `local/kokoro/gpu`, `runpod/kokoro/gpu`

2. Keep adapters pure - only synthesis logic, no infrastructure concerns

3. Set appropriate concurrency based on model size and available resources

4. For RunPod, ensure your Docker image includes all model weights to avoid download delays
