FROM bosonai/higgs-audio-vllm:latest
# remove the vLLM server
ENTRYPOINT []

WORKDIR /app

RUN pip install --no-cache-dir runpod

COPY yapit/ /app/yapit

ENV ADAPTER_CLASS=yapit.workers.adapters.higgs_audio_v2.HiggsAudioV2Adapter
CMD ["python", "-m", "yapit.workers.higgs_audio_v2"]
