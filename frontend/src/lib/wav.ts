/**
 * Minimal WAV (PCM 16-bit) encoder.
 *
 * Browser-side synthesis hands us raw float32 samples; the <audio> element needs a
 * container. Encoding once at synthesis — rather than holding the float32 and
 * re-encoding on every play — halves what the block cache carries.
 */

export function encodeWavPcm16(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const numChannels = 1;
  const bitDepth = 16;
  const headerSize = 44;
  const dataSize = samples.length * 2;

  const wavBuffer = new ArrayBuffer(headerSize + dataSize);
  const view = new DataView(wavBuffer);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(view, 8, "WAVE");

  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * numChannels * (bitDepth / 8), true);
  view.setUint16(32, numChannels * (bitDepth / 8), true);
  view.setUint16(34, bitDepth, true);

  writeAscii(view, 36, "data");
  view.setUint32(40, dataSize, true);

  const pcm = new Int16Array(wavBuffer, headerSize);
  for (let i = 0; i < samples.length; i++) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }

  return wavBuffer;
}

function writeAscii(view: DataView, offset: number, str: string): void {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}
