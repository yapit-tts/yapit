"""RunPod endpoint configurations."""

from infra.runpod.models import EndpointConfig, RunPodEndpoint, RunPodTemplate

HIGGS_NATIVE = EndpointConfig(
    template=RunPodTemplate(
        name="Yapit Higgs Audio V2 Native",
        imageName="maxw01/higgs-worker",  # tag added by deploy.py
        containerDiskInGb=25,
        env={
            "ADAPTER_CLASS": "yapit.workers.adapters.higgs_audio_v2_native.HiggsAudioV2NativeAdapter",
            "HIGGS_MODEL_PATH": "bosonai/higgs-audio-v2-generation-3B-base",
            "HIGGS_TOKENIZER_PATH": "bosonai/higgs-audio-v2-tokenizer",
            "HF_HOME": "/runpod-volume/huggingface-cache",
            "DEVICE": "cuda",
        },
        dockerStartCmd=["python", "-m", "yapit.workers.handlers.runpod"],
    ),
    endpoint=RunPodEndpoint(
        name="yapit-higgs-native",
        templateId="",
        gpuTypeIds=["AMPERE_24"],  # 24GB Ampere GPUs (RTX 3090, A5000, etc)
        workersMin=0,
        workersMax=2,
        model="https://huggingface.co/bosonai/higgs-audio-v2-generation-3B-base",
        scalerType="REQUEST_COUNT",
        scalerValue=10,
    ),
)

ENDPOINTS = {
    "higgs-native": HIGGS_NATIVE,
}
