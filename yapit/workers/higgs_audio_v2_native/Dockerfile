FROM runpod/pytorch:1.0.3-dev-dj-new-pytorch-cu1281-torch290-ubuntu2404

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    libsndfile1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install higgs-audio from our fork (proper packaging with all deps declared)
RUN uv pip install "boson-multimodal @ git+https://github.com/yapit-tts/higgs-audio.git" \
    --no-cache-dir --system --break-system-packages

# Install yapit worker deps
RUN uv pip install huggingface_hub "torchaudio~=2.9.0" "fastapi~=0.124.4" "uvicorn~=0.38.0" "runpod~=1.8.1" \
    --no-cache-dir --system --break-system-packages

# Download tokenizer into image (806MB - small enough to bake in)
# Main model (12GB) will download at runtime (cached by RunPod or local volume)
ENV HF_HOME=/models
RUN python -c "from huggingface_hub import snapshot_download; \
    print('Downloading tokenizer...'); \
    snapshot_download('bosonai/higgs-audio-v2-tokenizer', cache_dir='/models'); \
    print('Tokenizer download complete!')"

COPY yapit/ /app/yapit

ENV ADAPTER_CLASS=yapit.workers.adapters.higgs_audio_v2_native.HiggsAudioV2NativeAdapter
ENV HIGGS_MODEL_PATH=bosonai/higgs-audio-v2-generation-3B-base
ENV HIGGS_TOKENIZER_PATH=bosonai/higgs-audio-v2-tokenizer
ENV DEVICE=cuda
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "yapit.workers.higgs_audio_v2_native"]
