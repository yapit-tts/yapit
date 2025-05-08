class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferQueue = [];
    this.port.onmessage = (event) => {
      if (event.data.type === 'push') {
        this.bufferQueue.push(event.data.audioBuffer);
      }
    };
  }

  process(inputs, outputs) {
    const output = outputs[0];
    if (this.bufferQueue.length === 0) {
      // Output silence
      for (let channel = 0; channel < output.length; ++channel) {
        output[channel].fill(0);
      }
    } else {
      const buffer = this.bufferQueue.shift();
      for (let channel = 0; channel < output.length; ++channel) {
        const outputChannel = output[channel];
        const inputChannel = buffer[channel] || [];
        for (let i = 0; i < outputChannel.length; i++) {
          outputChannel[i] = inputChannel[i] || 0;
        }
      }
    }

    return true;
  }
}

registerProcessor('pcm-player-processor', PCMPlayerProcessor);

