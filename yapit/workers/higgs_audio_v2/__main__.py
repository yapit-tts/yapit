import uvicorn

from yapit.workers.handlers.local import create_app

if __name__ == "__main__":
    app = create_app("yapit.workers.adapters.higgs_audio_v2.HiggsAudioV2Adapter")
    uvicorn.run(app, host="0.0.0.0", port=8000)
