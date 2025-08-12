FROM bosonai/higgs-audio-vllm:latest

WORKDIR /app

RUN pip install --no-cache-dir runpod

# Pre-download models during build
ENV HF_HOME=/root/.cache/huggingface
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface/transformers
ENV VLLM_DOWNLOAD_DIR=/root/.cache/huggingface
ENV VLLM_CACHE_ROOT=/root/.cache/huggingface
RUN pip install --no-cache-dir huggingface_hub
RUN python3 -c "from huggingface_hub import snapshot_download; \
    print('Downloading model weights...'); \
    snapshot_download('bosonai/higgs-audio-v2-generation-3B-base', cache_dir='${VLLM_DOWNLOAD_DIR}'); \
    snapshot_download('bosonai/higgs-audio-v2-tokenizer', cache_dir='${VLLM_DOWNLOAD_DIR}'); \
    print('Model download complete!')"

# Install curl for health checks
RUN apt-get update && apt-get install -y curl
# Clean up to save space
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY yapit/ /app/yapit

COPY yapit/workers/higgs_audio_v2/start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV ADAPTER_CLASS=yapit.workers.adapters.higgs_audio_v2.HiggsAudioV2Adapter
ENV VLLM_STARTUP_TIMEOUT=300
ENV OMP_NUM_THREADS=2

# Build version - increment to trigger RunPod rebuild if only code changes
ENV YAPIT_BUILD_VERSION=2

ENTRYPOINT ["/app/start.sh"]
