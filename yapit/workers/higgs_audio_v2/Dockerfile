FROM bosonai/higgs-audio-vllm:latest

WORKDIR /app

RUN pip install --no-cache-dir runpod

# Set cache directories - can be overridden
ENV HF_HOME=/root/.cache/huggingface
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface/transformers
ENV VLLM_DOWNLOAD_DIR=/root/.cache/vllm

COPY yapit/ /app/yapit

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Create entrypoint script that starts both vLLM and RunPod handler
RUN cat > /app/start.sh << 'EOF'
#!/bin/bash
set -e

# Debug info
echo "Current directory: $(pwd)"
echo "Python path: $(which python3)"
echo "Contents of /app:"
ls -la /app/

# Start vLLM server in background
echo "Starting vLLM server..."
python3 -m vllm.entrypoints.bosonai.api_server \
  --served-model-name higgs-audio-v2-generation-3B-base \
  --model bosonai/higgs-audio-v2-generation-3B-base \
  --audio-tokenizer-type bosonai/higgs-audio-v2-tokenizer \
  --limit-mm-per-prompt audio=50 \
  --max-model-len 8192 \
  --port 8000 \
  --download-dir "${VLLM_DOWNLOAD_DIR}" \
  --disable-mm-preprocessor-cache &

VLLM_PID=$!

# Wait for vLLM server to be ready
echo "Waiting for vLLM server to be ready..."
for i in {1..120}; do
  if curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
    echo "vLLM server is ready!"
    break
  fi
  if ! kill -0 $VLLM_PID 2>/dev/null; then
    echo "vLLM server died unexpectedly"
    wait $VLLM_PID
    exit $?
  fi
  sleep 1
done

# Start RunPod handler
echo "Starting RunPod handler..."
exec python3 -m yapit.workers.handlers.runpod
EOF

RUN chmod +x /app/start.sh

ENV ADAPTER_CLASS=yapit.workers.adapters.higgs_audio_v2.HiggsAudioV2Adapter
ENTRYPOINT ["/app/start.sh"]
