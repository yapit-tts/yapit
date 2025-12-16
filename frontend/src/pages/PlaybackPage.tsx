import { SoundControl } from '@/components/soundControl';
import { DocumentCard } from '../components/documentCard';
import { useLocation } from "react-router";
import { useRef, useState, useEffect, useCallback } from "react";
import { useApi } from '@/api';
import { Loader2 } from "lucide-react";

interface Block {
  id: number;
  idx: number;
  text: string;
  est_duration_ms: number;
}

interface DocumentResponse {
  id: string;
  title: string | null;
  original_text: string;
  filtered_text: string | null;
  structured_content: string | null;
}

interface AudioBufferData {
  buffer: AudioBuffer;
  duration_ms: number;
}

const PlaybackPage = () => {
  const { state } = useLocation();
  const documentId: string | undefined = state?.documentId;
  const initialTitle: string | undefined = state?.documentTitle;

  const { api } = useApi();

  // Document data fetched from API
  const [document, setDocument] = useState<DocumentResponse | null>(null);
  const [documentBlocks, setDocumentBlocks] = useState<Block[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Derived state
  const documentTitle = document?.title ?? initialTitle;
  const documentContent = document?.filtered_text ?? document?.original_text ?? "";
  const numberOfBlocks = documentBlocks.length;
  const estimated_ms = documentBlocks.reduce((sum, b) => sum + (b.est_duration_ms || 0), 0);

  // Sound control variables
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
	const parentWidth = useRef<HTMLDivElement | null>(null);
	const [width, setWidth] = useState(0);
	const [volume, setVolume] = useState<number>(50); // Volume state (0-100)

  // Audio setup variables
  const audioContextRef = useRef<AudioContext | null>(null);
	const gainNodeRef = useRef<GainNode | null>(null);
	const [currentBlock, setCurrentBlock] = useState<number>(-1);
	const audioBuffersRef = useRef<Map<number, AudioBufferData>>(new Map());
	const currentSourceRef = useRef<AudioBufferSourceNode | null>(null);
	const [audioProgress, setAudioProgress] = useState<number>(0);
	const audioStartTimeRef = useRef<number>(0);
	const blockStartTimeRef = useRef<number>(0);
	const [actualTotalDuration, setActualTotalDuration] = useState<number>(0); // Track actual total duration
	const durationCorrectionsRef = useRef<Map<number, number>>(new Map()); // Track duration corrections per block
	const initialTotalEstimateRef = useRef<number>(0); // Store initial estimate

  // Fetch document and blocks on mount
  useEffect(() => {
    if (!documentId) {
      setError("No document ID provided");
      setIsLoading(false);
      return;
    }

    const fetchData = async () => {
      try {
        const [docResponse, blocksResponse] = await Promise.all([
          api.get<DocumentResponse>(`/v1/documents/${documentId}`),
          api.get<Block[]>(`/v1/documents/${documentId}/blocks`),
        ]);
        setDocument(docResponse.data);
        setDocumentBlocks(blocksResponse.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch document");
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [documentId, api]);

  // Initialize the AudioContext and set initial total duration
  useEffect(() => {
    const initAudio = async () => {
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext({ sampleRate: 24000 });
        // Create and connect gain node for volume control
        gainNodeRef.current = audioContextRef.current.createGain();
        gainNodeRef.current.connect(audioContextRef.current.destination);
        // Set initial volume
        gainNodeRef.current.gain.value = volume / 100;
			}
    };

    initAudio();
    
    // Calculate initial total duration from block estimates
    if (documentBlocks && documentBlocks.length > 0) {
      let totalEstimate = 0;
      for (const block of documentBlocks) {
        totalEstimate += block.est_duration_ms || 0;
      }
      initialTotalEstimateRef.current = totalEstimate;
      setActualTotalDuration(totalEstimate);
    } else if (estimated_ms) {
      // Fallback to document-level estimate if blocks not available
      initialTotalEstimateRef.current = estimated_ms;
      setActualTotalDuration(estimated_ms);
    }

    return () => {
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
    };
  }, [documentBlocks, estimated_ms]);

  // Update gain node value when volume changes
  useEffect(() => {
    if (gainNodeRef.current) {
      gainNodeRef.current.gain.value = volume / 100;
    }
  }, [volume]);

	// Track page width to pass to soundcontrol
	useEffect(() => {
    if (!parentWidth.current) return;
    const observer = new ResizeObserver(() => {
      setWidth(parentWidth.current?.offsetWidth || 0);
    });
    observer.observe(parentWidth.current);
    return () => observer.disconnect();
  }, []);

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
      
      const actualDurationMs = durationMs > 0 ? durationMs : Math.round(audioBuffer.duration * 1000);
      
      const audioBufferData: AudioBufferData = {
        buffer: audioBuffer,
        duration_ms: actualDurationMs
      };
      
      // Store in buffer map
      audioBuffersRef.current.set(blockId, audioBufferData);
      
      // Calculate and store duration correction
      if (documentBlocks && documentBlocks.length > 0) {
        const block = documentBlocks.find(b => b.id === blockId);
        if (block) {
          const estimatedDuration = block.est_duration_ms || 0;
          const actualDuration = actualDurationMs || 0;
          const correction = actualDuration - estimatedDuration;
          
          durationCorrectionsRef.current.set(blockId, correction);
          
          // Recalculate total if we have initial estimate
          if (initialTotalEstimateRef.current > 0) {
            const totalCorrection = Array.from(durationCorrectionsRef.current.values()).reduce((sum, corr) => sum + corr, 0);
            const newTotal = initialTotalEstimateRef.current + totalCorrection;
            setActualTotalDuration(newTotal);
          }
        }
      }
      
      return audioBufferData;
    } catch (error) {
      console.error("Error synthesizing block: ", error);
      setIsPlaying(false);
      return null;
    }
  }, [api, documentId, documentBlocks]);

  const playAudioBuffer = useCallback((audioBufferData: AudioBufferData) => {
    if (!audioContextRef.current) return;
    
    const source = audioContextRef.current.createBufferSource();
    source.buffer = audioBufferData.buffer;
    
    // Connect through gain node for volume control
    if (gainNodeRef.current) {
      source.connect(gainNodeRef.current);
    } else {
      // Fallback if gain node not initialized
      source.connect(audioContextRef.current.destination);
    }
    
    currentSourceRef.current = source;
    
    // Track timing for progress calculation
    audioStartTimeRef.current = audioContextRef.current.currentTime;
    
    source.onended = () => {
      currentSourceRef.current = null;
      
      // Calculate elapsed time for this block and add to total progress
      if (audioContextRef.current && audioStartTimeRef.current > 0) {
        const blockElapsed = (audioContextRef.current.currentTime - audioStartTimeRef.current) * 1000;
        blockStartTimeRef.current += blockElapsed;
      }
      
      // Check if we should move to next block or end playback
      setCurrentBlock(prev => {
        if (documentBlocks && prev < documentBlocks.length - 1) {
          return prev + 1;
        } else {
          // End of playback - reset everything
          setIsPlaying(false);
          setAudioProgress(0);
          audioStartTimeRef.current = 0;
          blockStartTimeRef.current = 0;
          return -1;
        }
      });
    };
    
    source.start(0);
  }, [documentBlocks]);

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
		
		// Play current block
		if (currentBlock < documentBlocks.length) {
			const currentBlockId = documentBlocks[currentBlock]?.id;
			if (!currentBlockId) return;
			
			const audioData = audioBuffersRef.current.get(currentBlockId);
			if (audioData) {
				playAudioBuffer(audioData);
			} else {
				// Synthesize and play current block
				synthesizeBlock(currentBlockId).then(audioData => {
					if (audioData && isPlaying) {
						playAudioBuffer(audioData);
					}
				});
			}
		}
	}, [currentBlock, isPlaying, documentBlocks, playAudioBuffer, synthesizeBlock]);

	// Track audio progress for time display
	useEffect(() => {
		let interval: NodeJS.Timeout;
		
		if (isPlaying && currentBlock >= 0 && audioContextRef.current && documentBlocks) {
			interval = setInterval(() => {
				if (audioContextRef.current && audioStartTimeRef.current > 0) {
					const currentTime = audioContextRef.current.currentTime;
					const elapsed = (currentTime - audioStartTimeRef.current) * 1000;
					const totalProgress = elapsed + blockStartTimeRef.current;
					setAudioProgress(totalProgress);
				}
			}, 100);
		}
		
		return () => {
			if (interval) clearInterval(interval);
		};
	}, [isPlaying, currentBlock, documentBlocks]);

  const handlePlay = async () => {
    if (isPlaying) return; // Prevent multiple plays
    
    setIsPlaying(true);
    
    if (currentBlock === -1) {
      // Start from beginning - reset all timing
      setCurrentBlock(0);
      setAudioProgress(0);
      audioStartTimeRef.current = 0;
      blockStartTimeRef.current = 0;
    }
  };

  const handlePause = () => {
    setIsPlaying(false);
    
    if (currentSourceRef.current) {
      currentSourceRef.current.stop();
      currentSourceRef.current = null;
    }
  };

  // Handle volume changes
  const handleVolumeChange = (newVolume: number) => {
    setVolume(newVolume);
  };

  if (isLoading) {
    return (
      <div className="flex grow items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex grow items-center justify-center text-destructive">
        {error}
      </div>
    );
  }

  return (
    <div className="flex grow" ref={parentWidth}>
      <DocumentCard title={documentTitle} content={documentContent} />
      <SoundControl
        isPlaying={isPlaying}
        onPlay={handlePlay}
        onPause={handlePause}
				style={{ width: `${width}px` }}
				progressBarValues={{estimated_ms: actualTotalDuration > 0 ? actualTotalDuration : estimated_ms, numberOfBlocks: numberOfBlocks, currentBlock: currentBlock >= 0 ? currentBlock : 0, setCurrentBlock: () => {}, audioProgress: audioProgress}}
				volume={volume}
				onVolumeChange={handleVolumeChange}
      />
    </div>
  );
};

export default PlaybackPage;