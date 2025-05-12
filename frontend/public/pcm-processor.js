class PCMProcessor extends AudioWorkletProcessor {
	constructor() {
    super();
    this.buffer = new Float32Array(0);
    this.readIndex = 0;
    
    this.port.onmessage = (e) => {
      const newData = new Float32Array(e.data);
      const temp = new Float32Array(this.buffer.length + newData.length);
      temp.set(this.buffer);
      temp.set(newData, this.buffer.length);
      this.buffer = temp;
    };
  }

  process(inputs, outputs) {
    const output = outputs[0];
    const blockSize = output[0].length;
    const available = this.buffer.length - this.readIndex;

    if (available >= blockSize) {
      for (let channel = 0; channel < output.length; channel++) {
        output[channel].set(
          this.buffer.subarray(this.readIndex, this.readIndex + blockSize)
        );
      }
      this.readIndex += blockSize;
    } else {
    }

    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor)
