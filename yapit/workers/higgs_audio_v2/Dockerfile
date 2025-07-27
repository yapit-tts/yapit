FROM bosonai/higgs-audio-vllm:latest
# remove the vLLM server
ENTRYPOINT []

WORKDIR /app

RUN pip install --no-cache-dir runpod huggingface_hub

# Set vLLM and HuggingFace cache directories
ENV HF_HOME=/root/.cache/huggingface
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface/transformers
ENV VLLM_DOWNLOAD_DIR=/root/.cache/vllm

# Pre-download the model weights during build
RUN python3 -c "from huggingface_hub import snapshot_download; \
    snapshot_download('bosonai/higgs-audio-v2-generation-3B-base', cache_dir='${HF_HOME}/hub'); \
    snapshot_download('bosonai/higgs-audio-v2-tokenizer', cache_dir='${HF_HOME}/hub')"

COPY yapit/ /app/yapit

ENV ADAPTER_CLASS=yapit.workers.adapters.higgs_audio_v2.HiggsAudioV2Adapter
CMD ["python3", "-m", "yapit.workers.higgs_audio_v2"]
