#!/bin/bash
set -e

# Configuration
VLLM_PORT=${VLLM_PORT:-8000}
# vLLM needs more time for model loading, compilation, and CUDA graph capture
VLLM_STARTUP_TIMEOUT=${VLLM_STARTUP_TIMEOUT:-300}

echo "=== Starting Higgs Audio V2 Worker ==="
echo "Current directory: $(pwd)"
echo "Python version: $(python3 --version)"
echo "VLLM cache dir: ${VLLM_DOWNLOAD_DIR}"

# Start vLLM server in background
echo "Starting vLLM server on port ${VLLM_PORT}..."
python3 -m vllm.entrypoints.bosonai.api_server \
  --served-model-name higgs-audio-v2-generation-3B-base \
  --model bosonai/higgs-audio-v2-generation-3B-base \
  --audio-tokenizer-type bosonai/higgs-audio-v2-tokenizer \
  --limit-mm-per-prompt audio=50 \
  --max-model-len 8192 \
  --port ${VLLM_PORT} \
  --download-dir "${VLLM_DOWNLOAD_DIR}" \
  --disable-mm-preprocessor-cache &

VLLM_PID=$!

# Function to cleanup on exit
cleanup() {
    echo "Shutting down vLLM server..."
    kill $VLLM_PID 2>/dev/null || true
    wait $VLLM_PID 2>/dev/null || true
}
trap cleanup EXIT

# Wait for vLLM server to be ready
echo "Waiting for vLLM server to be ready (timeout: ${VLLM_STARTUP_TIMEOUT}s)..."
for i in $(seq 1 $VLLM_STARTUP_TIMEOUT); do
  if curl -s http://localhost:${VLLM_PORT}/v1/models > /dev/null 2>&1; then
    echo "vLLM server is ready after ${i} seconds!"
    break
  fi
  
  # Check if vLLM process is still running
  if ! kill -0 $VLLM_PID 2>/dev/null; then
    echo "ERROR: vLLM server died unexpectedly!"
    wait $VLLM_PID
    exit_code=$?
    echo "vLLM exit code: $exit_code"
    exit $exit_code
  fi
  
  # Progress indicator every 10 seconds
  if [ $((i % 10)) -eq 0 ]; then
    echo "  Still waiting... ${i}s elapsed"
  fi
  
  sleep 1
done

# Check if timeout was reached
if [ $i -eq $VLLM_STARTUP_TIMEOUT ]; then
  echo "ERROR: vLLM server failed to start within ${VLLM_STARTUP_TIMEOUT} seconds"
  kill $VLLM_PID 2>/dev/null || true
  exit 1
fi

# Start RunPod handler (exec replaces current shell)
echo "Starting RunPod handler..."
exec python3 -m yapit.workers.handlers.runpod