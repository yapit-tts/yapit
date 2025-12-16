declare module "soundtouchjs" {
  export class PitchShifter {
    constructor(
      audioContext: AudioContext,
      audioBuffer: AudioBuffer,
      bufferSize: number
    );

    tempo: number;
    pitch: number;
    pitchSemitones: number;
    percentagePlayed: number;

    connect(node: AudioNode): void;
    disconnect(): void;
    on(event: "play", callback: (detail: { percentagePlayed: number; timePlayed: number; formattedTimePlayed: string }) => void): void;
    off(): void;
  }
}
