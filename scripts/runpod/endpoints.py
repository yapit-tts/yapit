# TODO This doesn't work with the Github deployment templates (yet?)... and setting up ghcr.io is a lot of overhead just for this (including way longer deploy times).
#  so the blow configuration not kept up to date but for future reference if we decide to use registry or it becomes available

"""RunPod endpoint configurations for all models."""

from scripts.runpod.models import EndpointConfig, RunPodEndpoint, RunPodTemplate

HIGGS_AUDIO_V2 = EndpointConfig(
    template=RunPodTemplate(
        name="Yapit Higgs Audio V2 TTS",
        imageName="GITHUB_TEMPLATE",  # Using RunPod GitHub integration
        containerDiskInGb=25,
        env={
            "ADAPTER_CLASS": "yapit.workers.adapters.higgs_audio_v2.HiggsAudioV2Adapter",
            "VLLM_STARTUP_TIMEOUT": "300",
            "VLLM_PORT": "8000",
        },
        dockerStartCmd="python3 -m yapit.workers.handlers.runpod",
    ),
    endpoint=RunPodEndpoint(
        name="yapit-higgs-audio-v2 -fb",  # Must match exactly what's in RunPod
        templateId="",  # Will be filled by deployment script
        gpuTypeIds=["NVIDIA RTX A5000", "NVIDIA L4", "NVIDIA GeForce RTX 3090"],
        workersMin=0,
        workersMax=1,
        scalerType="QUEUE_DELAY",
        scalerValue=4,
        executionTimeoutMs=600_000,  # higher for now so we dont fail due to cold starts or some bs
        idleTimeout=5,
        flashboot=True,
    ),
)

KOKORO_CPU = EndpointConfig(
    template=RunPodTemplate(
        name="Yapit Kokoro TTS CPU",
        imageName="ghcr.io/yapit-tts/yapit/kokoro-cpu:latest",
        containerDiskInGb=10,
        env={
            "ADAPTER_CLASS": "yapit.workers.adapters.kokoro.KokoroAdapter",
        },
        dockerStartCmd="python3 -m yapit.workers.handlers.runpod",
        containerRegistryAuthId=None,
    ),
    endpoint=RunPodEndpoint(
        name="kokoro-cpu",
        templateId="",
        gpuTypeIds=[],  # CPU endpoint
        workersMin=0,
        workersMax=1,
        scalerType="QUEUE_DELAY",
        scalerValue=4,
        executionTimeoutMs=120_000,
        idleTimeout=5,
        flashboot=False,
    ),
)

ENDPOINTS = {
    "higgs-audio-v2": HIGGS_AUDIO_V2,
    "kokoro-cpu": KOKORO_CPU,
}
