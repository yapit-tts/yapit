import { describe, it, expect } from "vitest";
import { encodeWavPcm16 } from "./wav";

const ascii = (buf: ArrayBuffer, offset: number, len: number) =>
  String.fromCharCode(...new Uint8Array(buf, offset, len));

describe("encodeWavPcm16", () => {
  it("writes a 44-byte mono PCM header describing the payload", () => {
    const samples = new Float32Array(100);
    const wav = encodeWavPcm16(samples, 24000);
    const dv = new DataView(wav);

    expect(ascii(wav, 0, 4)).toBe("RIFF");
    expect(ascii(wav, 8, 4)).toBe("WAVE");
    expect(ascii(wav, 12, 4)).toBe("fmt ");
    expect(ascii(wav, 36, 4)).toBe("data");

    expect(dv.getUint16(20, true)).toBe(1); // PCM
    expect(dv.getUint16(22, true)).toBe(1); // mono
    expect(dv.getUint32(24, true)).toBe(24000); // sample rate as given, never resampled
    expect(dv.getUint32(28, true)).toBe(24000 * 2); // byte rate
    expect(dv.getUint16(32, true)).toBe(2); // block align
    expect(dv.getUint16(34, true)).toBe(16); // bit depth

    expect(wav.byteLength).toBe(44 + 200);
    expect(dv.getUint32(4, true)).toBe(36 + 200); // RIFF size
    expect(dv.getUint32(40, true)).toBe(200); // data size
  });

  it("scales positive and negative samples against their different limits", () => {
    // Asymmetric on purpose: int16 reaches -32768 but only +32767.
    const wav = encodeWavPcm16(new Float32Array([0, 1, -1, 0.5, -0.5]), 24000);
    const pcm = new Int16Array(wav, 44);

    expect(Array.from(pcm)).toEqual([0, 32767, -32768, 16383, -16384]);
  });

  it("clamps samples outside [-1, 1] instead of wrapping", () => {
    const wav = encodeWavPcm16(new Float32Array([2, -2, 1.0001, -1.0001]), 24000);
    const pcm = new Int16Array(wav, 44);

    expect(Array.from(pcm)).toEqual([32767, -32768, 32767, -32768]);
  });

  it("carries the sample rate it is given", () => {
    for (const rate of [16000, 22050, 24000, 48000]) {
      const dv = new DataView(encodeWavPcm16(new Float32Array(4), rate));
      expect(dv.getUint32(24, true)).toBe(rate);
    }
  });
});
