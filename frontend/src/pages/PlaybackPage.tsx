import { SoundControl } from '@/components/soundControl';
import { DocumentCard } from '../components/documentCard';
import { useLocation } from "react-router";
import { useRef, useState, useEffect, useCallback } from "react";
import { useApi } from '@/api';

interface Block {
  id: number;
  idx: number;
  text: string;
  est_duration_ms: number;
}

interface ApiResponse {
  document_id: string;
	title: string;
  num_blocks: number;
  est_duration_ms: number;
  blocks: Block[];
}

interface AudioBufferData {
  buffer: AudioBuffer;
  duration_ms: number;
}

const PlaybackPage = () => {
  // State variables
  const { state } = useLocation();
  const apiResponse: ApiResponse | undefined = state?.apiResponse;
  const documentId: string | undefined = apiResponse?.document_id;
	const documentTitle: string | undefined = apiResponse?.title;
	const numberOfBlocks: number | undefined = apiResponse?.num_blocks;
  const documentBlocks: Block[] | undefined = apiResponse?.blocks;
  const inputText: string | undefined = state?.inputText;
	const estimated_ms: number | undefined = apiResponse?.est_duration_ms;



  // Sound control variables
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
	const parentWidth = useRef<HTMLDivElement | null>(null);
	const [width, setWidth] = useState(0);

  // Setup variables
	const { api } = useApi();
  const audioContextRef = useRef<AudioContext | null>(null);
	const [currentBlock, setCurrentBlock] = useState<number>(-1);
	const audioBuffersRef = useRef<Map<number, AudioBufferData>>(new Map());
	const currentSourceRef = useRef<AudioBufferSourceNode | null>(null);
	const [audioProgress, setAudioProgress] = useState<number>(0);
	const audioStartTimeRef = useRef<number>(0);
	const blockStartTimeRef = useRef<number>(0);
	const pausedAtRef = useRef<number>(0);
	const [isPaused, setIsPaused] = useState<boolean>(false);
	const isSeekingRef = useRef<boolean>(false); // Prevent audio overlap during seeking

  // Initialize the AudioWorklet
  useEffect(() => {
    const initWorklet = async () => {
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext({ sampleRate: 24000 });
			}
    };

    initWorklet();

    return () => {
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
    };
  }, []);

	// Track page width to pass to playbar
	useEffect(() => {
    if (!parentWidth.current) return;
    const observer = new ResizeObserver(() => {
      setWidth(parentWidth.current?.offsetWidth || 0);
    });
    observer.observe(parentWidth.current);
    return () => observer.disconnect();
  }, []);



  // Handle play/pause state changes
  useEffect(() => {
    if (!audioContextRef.current) return;
    
    if (isPlaying) {
      if (audioContextRef.current.state === 'suspended') {
        audioContextRef.current.resume().catch(err => {
          console.error('Failed to resume AudioContext:', err);
          setIsPlaying(false);
        });
      }
    } else {
      if (audioContextRef.current.state === 'running') {
        audioContextRef.current.suspend().catch(err => {
          console.error('Failed to suspend AudioContext:', err);
        });
      }
    }
  }, [isPlaying]);

  const synthesizeBlock = useCallback(async (blockId: number): Promise<AudioBufferData | null> => {
    try {
      const response = await api.post(`/v1/documents/${documentId}/blocks/${blockId}/synthesize`, {
        "model_slug": "kokoro",
        "voice_slug": "af_heart",
        "speed": 1,
      }, {
        responseType: 'arraybuffer'
      });
      
      const arrayBuffer = response.data;
      const sampleRate = parseInt(response.headers['x-sample-rate'] || '24000');
      const channels = parseInt(response.headers['x-channels'] || '1');
      const codec = response.headers['x-audio-codec'] || 'pcm';
      const durationMs = parseInt(response.headers['x-duration-ms'] || '0');
      
      if (!audioContextRef.current) {
        console.error("AudioContext not initialized");
        return null;
      }
      
      let audioBuffer: AudioBuffer;
      
      if (codec === 'pcm') {
        // Handle raw PCM data
        const pcmData = new Int16Array(arrayBuffer);
        const frames = pcmData.length / channels;
        
        audioBuffer = audioContextRef.current.createBuffer(channels, frames, sampleRate);
        
        // Convert Int16 PCM to Float32 and copy to audio buffer
        for (let channel = 0; channel < channels; channel++) {
          const channelData = audioBuffer.getChannelData(channel);
          for (let frame = 0; frame < frames; frame++) {
            const sampleIndex = frame * channels + channel;
            channelData[frame] = pcmData[sampleIndex] / 32768.0; // Convert to [-1, 1] range
          }
        }
      } else {
        // Handle encoded audio formats (WAV, MP3, OGG, etc.)
        audioBuffer = await audioContextRef.current.decodeAudioData(arrayBuffer);
      }
      const audioBufferData: AudioBufferData = {
        buffer: audioBuffer,
        duration_ms: durationMs
      };
      
      // Store in buffer map
      audioBuffersRef.current.set(blockId, audioBufferData);
      
      return audioBufferData;
    } catch (error) {
      console.error("Error synthesizing block: ", error);
      setIsPlaying(false);
      return null;
    }
  }, [api, documentId]);

  const playAudioBuffer = useCallback((audioBufferData: AudioBufferData, offset: number = 0) => {
    if (!audioContextRef.current) return;
    
    const source = audioContextRef.current.createBufferSource();
    source.buffer = audioBufferData.buffer;
    source.connect(audioContextRef.current.destination);
    
    currentSourceRef.current = source;
    
    // Track timing for progress calculation
    audioStartTimeRef.current = audioContextRef.current.currentTime;
    console.log('Starting audio playback at time:', audioStartTimeRef.current, 'for block:', currentBlock);
    
    source.onended = () => {
      currentSourceRef.current = null;
      
      // Calculate elapsed time for this block and add to total progress
      if (audioContextRef.current && audioStartTimeRef.current > 0) {
        const blockElapsed = (audioContextRef.current.currentTime - audioStartTimeRef.current) * 1000;
        blockStartTimeRef.current += blockElapsed;
        pausedAtRef.current = 0; // Reset pause position when block completes
      }
      
      // Check if we should move to next block or end playback
      setCurrentBlock(prev => {
        if (documentBlocks && prev < documentBlocks.length - 1) {
          return prev + 1;
        } else {
          // End of playback - reset everything
          setIsPlaying(false);
          setIsPaused(false);
          setAudioProgress(0);
          audioStartTimeRef.current = 0;
          blockStartTimeRef.current = 0;
          pausedAtRef.current = 0;
          return -1;
        }
      });
    };
    
    // Start playing from the specified offset (for resume functionality)
    source.start(0, offset);
  }, [documentBlocks, currentBlock]);

	// Handle block changes and pre-synthesis
	useEffect(() => {
		if (!documentBlocks || currentBlock === -1 || !isPlaying) return;
		
		// Pre-synthesize next block if not the last block
		if (currentBlock < (documentBlocks.length - 1)) {
			const nextBlockId = documentBlocks[currentBlock + 1].id;
			if (!audioBuffersRef.current.has(nextBlockId)) {
				synthesizeBlock(nextBlockId);
			}
		}
		
		// Auto-play current block if we moved due to natural progression
		// Don't auto-play if user is seeking via slider or if it's the first block (handled in handlePlay)
		if (currentBlock > 0 && isPlaying && !isPaused) {
			// Reset timing when moving to a new block naturally
			if (currentSourceRef.current) {
				currentSourceRef.current.stop();
				currentSourceRef.current = null;
			}
			
			// Calculate progress up to this block
			let progressUpToBlock = 0;
			for (let i = 0; i < currentBlock && i < documentBlocks.length; i++) {
				const block = documentBlocks[i];
				if (block && block.id) {
					const blockData = audioBuffersRef.current.get(block.id);
					if (blockData && blockData.duration_ms > 0) {
						progressUpToBlock += blockData.duration_ms;
					}
				}
			}
			blockStartTimeRef.current = progressUpToBlock;
			pausedAtRef.current = 0; // Reset pause position for new block
			
			// Block change handled by effect below
			
			// Make sure currentBlock is within bounds
			if (currentBlock >= documentBlocks.length) {
				return;
			}
			
			const currentBlockId = documentBlocks[currentBlock]?.id;
			if (!currentBlockId) {
				return;
			}
			
			const audioData = audioBuffersRef.current.get(currentBlockId);
			if (audioData) {
				playAudioBuffer(audioData, 0);
			} else {
				// Synthesize and play current block
				synthesizeBlock(currentBlockId).then(audioData => {
					if (audioData && isPlaying) {
						playAudioBuffer(audioData, 0);
					}
				});
			}
		}
	}, [currentBlock, isPlaying, isPaused, documentBlocks, playAudioBuffer, synthesizeBlock]);

	// Track audio progress for time display
	useEffect(() => {
		let interval: NodeJS.Timeout;
		
		if (isPlaying && currentBlock >= 0 && audioContextRef.current && documentBlocks) {
			interval = setInterval(() => {
				if (audioContextRef.current && audioStartTimeRef.current > 0) {
					const currentTime = audioContextRef.current.currentTime;
					const elapsed = (currentTime - audioStartTimeRef.current) * 1000;
					const totalProgress = elapsed + blockStartTimeRef.current + pausedAtRef.current;
					setAudioProgress(totalProgress);
					
					// Log occasionally to debug
					if (Math.random() < 0.05) {
						console.log('Progress:', {
							currentBlock,
							audioStartTime: audioStartTimeRef.current,
							currentTime,
							elapsed,
							totalProgress
						});
					}
				}
			}, 100);
		} else if (isPaused) {
			// Keep showing paused progress
			const totalProgress = pausedAtRef.current + blockStartTimeRef.current;
			setAudioProgress(totalProgress);
		}
		
		return () => {
			if (interval) clearInterval(interval);
		};
	}, [isPlaying, currentBlock, isPaused, documentBlocks]);

  const handlePlay = async () => {
    setIsPlaying(true);
    setIsPaused(false);
    
    if (currentBlock === -1) {
      // Start from beginning - reset all timing
      setCurrentBlock(0);
      setAudioProgress(0);
      audioStartTimeRef.current = 0;
      blockStartTimeRef.current = 0;
      pausedAtRef.current = 0;
      const audioData = await synthesizeBlock(documentBlocks?.[0]?.id || 0);
      if (audioData) {
        playAudioBuffer(audioData, 0);
      }
    } else if (isPaused) {
      // Resume from paused position
      const audioData = audioBuffersRef.current.get(documentBlocks?.[currentBlock]?.id || 0);
      if (audioData) {
        // Calculate offset in seconds for resuming
        const offsetSeconds = pausedAtRef.current / 1000;
        playAudioBuffer(audioData, offsetSeconds);
      } else {
        // Re-synthesize current block if not in buffer
        const audioData = await synthesizeBlock(documentBlocks?.[currentBlock]?.id || 0);
        if (audioData) {
          const offsetSeconds = pausedAtRef.current / 1000;
          playAudioBuffer(audioData, offsetSeconds);
        }
      }
    } else {
      // Resume from current block (not paused, just replaying)
      const audioData = audioBuffersRef.current.get(documentBlocks?.[currentBlock]?.id || 0);
      if (audioData) {
        playAudioBuffer(audioData, 0);
      } else {
        // Re-synthesize current block if not in buffer
        const audioData = await synthesizeBlock(documentBlocks?.[currentBlock]?.id || 0);
        if (audioData) {
          playAudioBuffer(audioData, 0);
        }
      }
    }
  };

  const handlePause = () => {
    setIsPlaying(false);
    setIsPaused(true);
    
    if (currentSourceRef.current && audioContextRef.current) {
      // Calculate how much of the current block has been played
      const elapsed = (audioContextRef.current.currentTime - audioStartTimeRef.current) * 1000;
      pausedAtRef.current = elapsed; // Store where we paused within the current block
      
      currentSourceRef.current.stop();
      currentSourceRef.current = null;
    }
  };

  const handleSeekToBlock = async (targetBlock: number) => {
    // Round to nearest integer block
    targetBlock = Math.round(targetBlock);
    
    if (targetBlock === currentBlock || isSeekingRef.current) return; // No change or already seeking
    
    isSeekingRef.current = true;
    
    // Stop current playback
    if (currentSourceRef.current) {
      currentSourceRef.current.stop();
      currentSourceRef.current = null;
    }
    
    // Calculate progress up to the target block
    let progressUpToBlock = 0;
    if (documentBlocks) {
      for (let i = 0; i < targetBlock && i < documentBlocks.length; i++) {
        const block = documentBlocks[i];
        if (block && block.id) {
          const blockData = audioBuffersRef.current.get(block.id);
          if (blockData) {
            progressUpToBlock += blockData.duration_ms;
          }
        }
      }
    }
    
    blockStartTimeRef.current = progressUpToBlock;
    pausedAtRef.current = 0; // Start from beginning of the target block
    
    setCurrentBlock(targetBlock);
    
    // If we were playing, start playing the new block
    if (isPlaying && !isPaused && documentBlocks) {
      const targetBlockId = documentBlocks[targetBlock]?.id;
      if (targetBlockId) {
        let audioData = audioBuffersRef.current.get(targetBlockId);
        if (!audioData) {
          audioData = await synthesizeBlock(targetBlockId);
        }
        if (audioData) {
          playAudioBuffer(audioData, 0);
        }
      }
    }
    
    isSeekingRef.current = false;
  };

  return (
    <div className="flex grow" ref={parentWidth}>
      <DocumentCard title={documentTitle} inputText={inputText} />
      <SoundControl 
        isPlaying={isPlaying} 
        onPlay={handlePlay} 
        onPause={handlePause}
				style={{ width: `${width}px` }}
				progressBarValues={{estimated_ms: estimated_ms, numberOfBlocks: numberOfBlocks, currentBlock: currentBlock >= 0 ? currentBlock : 0, setCurrentBlock: handleSeekToBlock, audioProgress: audioProgress}}	
      />
    </div>
  );
};

export default PlaybackPage;

