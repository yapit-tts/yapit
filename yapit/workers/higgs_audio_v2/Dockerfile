FROM bosonai/higgs-audio-vllm:latest

WORKDIR /app

RUN pip install --no-cache-dir runpod

# Set cache directories - can be overridden
ENV HF_HOME=/root/.cache/huggingface
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface/transformers
ENV VLLM_DOWNLOAD_DIR=/root/.cache/vllm

# Pre-download models during build
RUN pip install --no-cache-dir huggingface_hub
RUN python3 -c "from huggingface_hub import snapshot_download; \
    print('Downloading model weights...'); \
    snapshot_download('bosonai/higgs-audio-v2-generation-3B-base', cache_dir='${HF_HOME}/hub'); \
    snapshot_download('bosonai/higgs-audio-v2-tokenizer', cache_dir='${HF_HOME}/hub'); \
    print('Model download complete!')"

# Clean up to save space
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY yapit/ /app/yapit

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy startup script
COPY yapit/workers/higgs_audio_v2/start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV ADAPTER_CLASS=yapit.workers.adapters.higgs_audio_v2.HiggsAudioV2Adapter
ENV VLLM_STARTUP_TIMEOUT=300
ENTRYPOINT ["/app/start.sh"]
