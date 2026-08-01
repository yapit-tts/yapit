/**
 * AudioPlayer: Pitch-preserving audio playback using browser native preservesPitch
 *
 * Plays audio directly through HTMLAudioElement (no Web Audio routing).
 * Previous approach routed through MediaElementAudioSourceNode → GainNode → AudioContext,
 * which caused glitchy/choppy audio on iOS Safari (WebKit bug 211394).
 */

// Minimal valid WAV: 1 silent sample, mono 16-bit 44100Hz (46 bytes)
const SILENT_WAV = "data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==";

const LOAD_TIMEOUT_MS = 5_000;

/** A load that stop() (or a newer load) superseded. The caller no longer owns the element. */
export class StaleLoadError extends Error {}

/** The browser loaded the audio but can't tell us how long it is — the container is unusable. */
export class UnplayableAudioError extends Error {}

export class AudioPlayer {
  private audioElement: HTMLAudioElement;
  private _tempo = 1.0;
  private onEndedCallback?: () => void;
  private onProgressCallback?: (percentPlayed: number, durationMs: number) => void;
  private progressInterval: ReturnType<typeof setInterval> | null = null;
  private currentBlobUrl: string | null = null;
  private currentDurationMs = 0;
  private unlocked = false;
  private cancelPendingLoad: (() => void) | null = null;

  constructor() {
    this.audioElement = document.createElement("audio");
    this.audioElement.preservesPitch = true;

    this.audioElement.addEventListener("ended", () => {
      this.stopProgressTracking();
      this.onEndedCallback?.();
    });
  }

  /**
   * Unlock the audio element for programmatic playback on mobile.
   * Must be called in a user gesture context (tap/click handler).
   * After a successful unlock, future play() calls work without gestures.
   */
  unlock(): Promise<void> {
    if (this.unlocked) return Promise.resolve();
    console.debug("[AudioPlayer] unlock: attempting");
    this.audioElement.src = SILENT_WAV;
    return this.audioElement.play()
      .then(() => {
        this.audioElement.pause();
        this.audioElement.currentTime = 0;
        this.unlocked = true;
        console.debug("[AudioPlayer] unlock: success");
      })
      .catch(() => {
        console.debug("[AudioPlayer] unlock: blocked, will retry on next gesture");
      });
  }

  /** Load encoded audio bytes (OGG Opus from the server, WAV from browser synthesis). Returns actual duration in ms. */
  loadRawAudio(data: ArrayBuffer, mimeType: string): Promise<number> {
    this.stop();

    const blob = new Blob([data], { type: mimeType });
    this.currentBlobUrl = URL.createObjectURL(blob);

    return this.waitForCanPlayThrough(mimeType).then(() => {
      const duration = this.audioElement.duration;
      // A container the browser can't length reports Infinity/NaN here. Letting that
      // through would silently poison progress and remaining-time for the whole session.
      if (!Number.isFinite(duration)) {
        throw new UnplayableAudioError(`[AudioPlayer] Non-finite duration (${duration}) for ${mimeType}`);
      }
      this.currentDurationMs = Math.round(duration * 1000);
      return this.currentDurationMs;
    });
  }

  private waitForCanPlayThrough(mimeType: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const cleanup = () => {
        this.audioElement.removeEventListener("canplaythrough", onCanPlay);
        this.audioElement.removeEventListener("error", onError);
        clearTimeout(timer);
        this.cancelPendingLoad = null;
      };

      const onCanPlay = () => { cleanup(); resolve(); };
      const onError = () => {
        cleanup();
        // MEDIA_ERR_SRC_NOT_SUPPORTED: the browser can't decode this container at all,
        // so no block of this document will play. Anything else may be one bad block.
        const code = this.audioElement.error?.code;
        if (code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
          reject(new UnplayableAudioError(`[AudioPlayer] Unsupported container: ${mimeType}`));
          return;
        }
        reject(new Error(`[AudioPlayer] Audio element error during load (code ${code})`));
      };
      const timer = setTimeout(() => {
        console.debug("[AudioPlayer] waitForCanPlayThrough: timeout", { LOAD_TIMEOUT_MS });
        cleanup();
        reject(new Error("[AudioPlayer] Load timeout — canplaythrough not fired"));
      }, LOAD_TIMEOUT_MS);

      // Without this, a superseded load keeps its listeners and timer: it either resolves off
      // the *next* block's canplaythrough, or times out and looks like a genuine failure.
      this.cancelPendingLoad = () => {
        cleanup();
        reject(new StaleLoadError("[AudioPlayer] Load superseded"));
      };

      this.audioElement.addEventListener("canplaythrough", onCanPlay);
      this.audioElement.addEventListener("error", onError);
      this.audioElement.src = this.currentBlobUrl!;
      this.audioElement.playbackRate = this._tempo;
    });
  }

  async play(): Promise<void> {
    try {
      await this.audioElement.play();
      console.debug("[AudioPlayer] play: started");
      this.startProgressTracking();
    } catch (err) {
      console.debug("[AudioPlayer] play: rejected", { error: (err as Error).name, message: (err as Error).message });
      throw err;
    }
  }

  pause(): void {
    this.audioElement.pause();
    this.stopProgressTracking();
  }

  stop(): void {
    this.cancelPendingLoad?.();
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

  getCurrentTime(): number {
    return this.audioElement.currentTime;
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
}
