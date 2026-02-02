/**
 * AudioPlayer: Pitch-preserving audio playback using browser native preservesPitch
 */

export interface AudioPlayerOptions {
  audioContext: AudioContext;
  gainNode: GainNode;
  onEnded?: () => void;
  onProgress?: (percentPlayed: number, durationMs: number) => void;
}

export class AudioPlayer {
  private audioContext: AudioContext;
  private gainNode: GainNode;
  private audioElement: HTMLAudioElement;
  private mediaSource: MediaElementAudioSourceNode | null = null;
  private _tempo = 1.0;
  private onEndedCallback?: () => void;
  private onProgressCallback?: (percentPlayed: number, durationMs: number) => void;
  private progressInterval: ReturnType<typeof setInterval> | null = null;
  private currentBlobUrl: string | null = null;
  private currentDurationMs = 0;

  constructor(options: AudioPlayerOptions) {
    this.audioContext = options.audioContext;
    this.gainNode = options.gainNode;
    this.onEndedCallback = options.onEnded;
    this.onProgressCallback = options.onProgress;

    // Create audio element
    this.audioElement = document.createElement("audio");
    this.audioElement.preservesPitch = true;

    // Connect to Web Audio for volume control
    this.mediaSource = this.audioContext.createMediaElementSource(this.audioElement);
    this.mediaSource.connect(this.gainNode);

    // Handle playback end
    this.audioElement.addEventListener("ended", () => {
      this.stopProgressTracking();
      this.onEndedCallback?.();
    });
  }

  /**
   * Load an AudioBuffer and prepare for playback.
   * Returns a promise that resolves when audio is ready to play.
   */
  load(buffer: AudioBuffer): Promise<void> {
    this.stop();
    this.currentDurationMs = Math.round(buffer.duration * 1000);

    // Convert AudioBuffer to WAV blob
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

  /**
   * Start or resume playback
   */
  async play(): Promise<void> {
    if (this.audioContext.state === "suspended") {
      await this.audioContext.resume();
    }

    try {
      await this.audioElement.play();
      this.startProgressTracking();
    } catch (err) {
      console.error("[AudioPlayer] play() failed:", err);
    }
  }

  /**
   * Pause playback
   */
  pause(): void {
    this.audioElement.pause();
    this.stopProgressTracking();
  }

  /**
   * Stop and clean up
   */
  stop(): void {
    this.audioElement.pause();
    this.audioElement.currentTime = 0;
    this.stopProgressTracking();

    // Clean up blob URL
    if (this.currentBlobUrl) {
      URL.revokeObjectURL(this.currentBlobUrl);
      this.currentBlobUrl = null;
    }
  }

  /**
   * Set playback tempo (speed) without affecting pitch
   * @param tempo - 0.5 to 3.0 (1.0 = normal speed)
   */
  setTempo(tempo: number): void {
    this._tempo = Math.max(0.5, Math.min(3.0, tempo));
    this.audioElement.playbackRate = this._tempo;
  }

  get tempo(): number {
    return this._tempo;
  }

  get isPlaying(): boolean {
    return !this.audioElement.paused;
  }

  /**
   * Update callbacks after construction
   */
  setOnEnded(callback: () => void): void {
    this.onEndedCallback = callback;
  }

  setOnProgress(callback: (percentPlayed: number, durationMs: number) => void): void {
    this.onProgressCallback = callback;
  }

  private startProgressTracking(): void {
    this.stopProgressTracking();

    // Update progress ~10 times per second
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

  /**
   * Convert AudioBuffer to WAV Blob
   */
  private audioBufferToWav(buffer: AudioBuffer): Blob {
    const numChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const format = 1; // PCM
    const bitDepth = 16;

    // Interleave channels
    const length = buffer.length * numChannels;
    const samples = new Int16Array(length);

    for (let channel = 0; channel < numChannels; channel++) {
      const channelData = buffer.getChannelData(channel);
      for (let i = 0; i < buffer.length; i++) {
        // Clamp and convert to Int16
        const sample = Math.max(-1, Math.min(1, channelData[i]));
        samples[i * numChannels + channel] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      }
    }

    // Create WAV file
    const dataSize = samples.length * 2;
    const headerSize = 44;
    const wavBuffer = new ArrayBuffer(headerSize + dataSize);
    const view = new DataView(wavBuffer);

    // RIFF header
    this.writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    this.writeString(view, 8, "WAVE");

    // fmt chunk
    this.writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true); // chunk size
    view.setUint16(20, format, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * (bitDepth / 8), true); // byte rate
    view.setUint16(32, numChannels * (bitDepth / 8), true); // block align
    view.setUint16(34, bitDepth, true);

    // data chunk
    this.writeString(view, 36, "data");
    view.setUint32(40, dataSize, true);

    // Write samples
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
