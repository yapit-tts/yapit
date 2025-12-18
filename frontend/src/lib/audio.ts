/**
 * AudioPlayer: Pitch-preserving audio playback using SoundTouchJS
 *
 * Wraps SoundTouchJS PitchShifter to enable speed changes without pitch shift.
 * The native Web Audio API playbackRate causes chipmunk effect at higher speeds.
 */

import { PitchShifter } from "soundtouchjs";

export interface AudioPlayerOptions {
  audioContext: AudioContext;
  gainNode: GainNode;
  onEnded?: () => void;
  onProgress?: (percentPlayed: number, durationMs: number) => void;
}

export class AudioPlayer {
  private audioContext: AudioContext;
  private gainNode: GainNode;
  private shifter: PitchShifter | null = null;
  private isConnected = false;
  private _tempo = 1.0;
  private onEndedCallback?: () => void;
  private onProgressCallback?: (percentPlayed: number, durationMs: number) => void;
  private hasEnded = false;
  private currentBufferDurationMs = 0;

  constructor(options: AudioPlayerOptions) {
    this.audioContext = options.audioContext;
    this.gainNode = options.gainNode;
    this.onEndedCallback = options.onEnded;
    this.onProgressCallback = options.onProgress;
  }

  /**
   * Load an AudioBuffer and prepare for playback
   */
  load(buffer: AudioBuffer): void {
    this.stop();
    this.hasEnded = false;
    this.currentBufferDurationMs = Math.round(buffer.duration * 1000);

    // PitchShifter: (audioContext, audioBuffer, bufferSize)
    // Larger buffer (16384) reduces choppiness but adds latency
    this.shifter = new PitchShifter(this.audioContext, buffer, 16384);
    this.shifter.tempo = this._tempo;

    this.shifter.on("play", (detail: { percentagePlayed: number }) => {
      this.onProgressCallback?.(detail.percentagePlayed, this.currentBufferDurationMs);

      // Detect end of playback (>= 99.5% to handle floating point)
      if (detail.percentagePlayed >= 99.5 && !this.hasEnded) {
        this.hasEnded = true;
        // Calculate remaining audio time + buffer margin before disconnecting
        const remainingPercent = 100 - detail.percentagePlayed;
        const remainingMs = (remainingPercent / 100) * this.currentBufferDurationMs;
        // Add margin for SoundTouchJS buffer (16384 samples @ 44100Hz = ~372ms)
        // and account for tempo (faster = less buffer time needed)
        const bufferMarginMs = Math.ceil(400 / this._tempo);
        const delayMs = Math.max(50, remainingMs + bufferMarginMs);

        setTimeout(() => {
          if (this.hasEnded) {
            this.disconnect();
            this.onEndedCallback?.();
          }
        }, delayMs);
      }
    });
  }

  /**
   * Start or resume playback
   */
  play(): void {
    if (!this.shifter || this.isConnected) return;

    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
    }

    this.shifter.connect(this.gainNode);
    this.isConnected = true;
  }

  /**
   * Pause playback (disconnect from output)
   */
  pause(): void {
    this.disconnect();
  }

  /**
   * Stop and clean up
   */
  stop(): void {
    this.disconnect();
    if (this.shifter) {
      this.shifter.off();
      this.shifter = null;
    }
    this.hasEnded = false;
  }

  /**
   * Set playback tempo (speed) without affecting pitch
   * @param tempo - 0.5 to 3.0 (1.0 = normal speed)
   */
  setTempo(tempo: number): void {
    this._tempo = Math.max(0.5, Math.min(3.0, tempo));
    if (this.shifter) {
      this.shifter.tempo = this._tempo;
    }
  }

  get tempo(): number {
    return this._tempo;
  }

  get isPlaying(): boolean {
    return this.isConnected;
  }

  /**
   * Update callbacks after construction
   */
  setOnEnded(callback: () => void): void {
    this.onEndedCallback = callback;
  }

  private disconnect(): void {
    if (this.shifter && this.isConnected) {
      try {
        this.shifter.disconnect();
      } catch {
        // Ignore if already disconnected
      }
      this.isConnected = false;
    }
  }
}
