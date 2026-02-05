/**
 * AudioPlayer: Pitch-preserving audio playback using browser native preservesPitch
 *
 * Plays audio directly through HTMLAudioElement (no Web Audio routing).
 * Previous approach routed through MediaElementAudioSourceNode → GainNode → AudioContext,
 * which caused glitchy/choppy audio on iOS Safari (WebKit bug 211394).
 */

export class AudioPlayer {
  private audioElement: HTMLAudioElement;
  private _tempo = 1.0;
  private onEndedCallback?: () => void;
  private onProgressCallback?: (percentPlayed: number, durationMs: number) => void;
  private progressInterval: ReturnType<typeof setInterval> | null = null;
  private currentBlobUrl: string | null = null;
  private currentDurationMs = 0;

  constructor() {
    this.audioElement = document.createElement("audio");
    this.audioElement.preservesPitch = true;

    this.audioElement.addEventListener("ended", () => {
      this.stopProgressTracking();
      this.onEndedCallback?.();
    });
  }

  load(buffer: AudioBuffer): Promise<void> {
    this.stop();
    this.currentDurationMs = Math.round(buffer.duration * 1000);

    const wavBlob = this.audioBufferToWav(buffer);
    this.currentBlobUrl = URL.createObjectURL(wavBlob);

    return new Promise((resolve) => {
      const onCanPlay = () => {
        this.audioElement.removeEventListener("canplaythrough", onCanPlay);
        resolve();
      };
      this.audioElement.addEventListener("canplaythrough", onCanPlay);
      this.audioElement.src = this.currentBlobUrl!;
      this.audioElement.playbackRate = this._tempo;
    });
  }

  async play(): Promise<void> {
    try {
      await this.audioElement.play();
      this.startProgressTracking();
    } catch (err) {
      console.error("[AudioPlayer] play() failed:", err);
    }
  }

  pause(): void {
    this.audioElement.pause();
    this.stopProgressTracking();
  }

  stop(): void {
    this.audioElement.pause();
    this.audioElement.currentTime = 0;
    this.stopProgressTracking();

    if (this.currentBlobUrl) {
      URL.revokeObjectURL(this.currentBlobUrl);
      this.currentBlobUrl = null;
    }
  }

  setTempo(tempo: number): void {
    this._tempo = Math.max(0.5, Math.min(3.0, tempo));
    this.audioElement.playbackRate = this._tempo;
  }

  setVolume(volume: number): void {
    this.audioElement.volume = Math.max(0, Math.min(1, volume));
  }

  get tempo(): number {
    return this._tempo;
  }

  get isPlaying(): boolean {
    return !this.audioElement.paused;
  }

  setOnEnded(callback: () => void): void {
    this.onEndedCallback = callback;
  }

  setOnProgress(callback: (percentPlayed: number, durationMs: number) => void): void {
    this.onProgressCallback = callback;
  }

  private startProgressTracking(): void {
    this.stopProgressTracking();

    this.progressInterval = setInterval(() => {
      if (this.audioElement.duration > 0) {
        const percent = (this.audioElement.currentTime / this.audioElement.duration) * 100;
        this.onProgressCallback?.(percent, this.currentDurationMs);
      }
    }, 100);
  }

  private stopProgressTracking(): void {
    if (this.progressInterval) {
      clearInterval(this.progressInterval);
      this.progressInterval = null;
    }
  }

  private audioBufferToWav(buffer: AudioBuffer): Blob {
    const numChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const format = 1; // PCM
    const bitDepth = 16;

    const length = buffer.length * numChannels;
    const samples = new Int16Array(length);

    for (let channel = 0; channel < numChannels; channel++) {
      const channelData = buffer.getChannelData(channel);
      for (let i = 0; i < buffer.length; i++) {
        const sample = Math.max(-1, Math.min(1, channelData[i]));
        samples[i * numChannels + channel] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      }
    }

    const dataSize = samples.length * 2;
    const headerSize = 44;
    const wavBuffer = new ArrayBuffer(headerSize + dataSize);
    const view = new DataView(wavBuffer);

    this.writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    this.writeString(view, 8, "WAVE");

    this.writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, format, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * (bitDepth / 8), true);
    view.setUint16(32, numChannels * (bitDepth / 8), true);
    view.setUint16(34, bitDepth, true);

    this.writeString(view, 36, "data");
    view.setUint32(40, dataSize, true);

    const wavSamples = new Int16Array(wavBuffer, headerSize);
    wavSamples.set(samples);

    return new Blob([wavBuffer], { type: "audio/wav" });
  }

  private writeString(view: DataView, offset: number, str: string): void {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }
}
