import { SoundControl } from '@/components/soundControl';
import { DocumentCard } from '../components/documentCard';
import { useLocation } from "react-router";
import { useRef, useState, useEffect, useCallback } from "react";
import { useApi } from '@/api';
import { Loader2 } from "lucide-react";
import { AudioPlayer } from '@/lib/audio';

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
  const isPlayingRef = useRef<boolean>(false); // Ref to track current state for async callbacks
  const [volume, setVolume] = useState<number>(50);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.0);
  const [isSynthesizing, setIsSynthesizing] = useState<boolean>(false);

  // Audio setup variables
  const audioContextRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const audioPlayerRef = useRef<AudioPlayer | null>(null);
  const [currentBlock, setCurrentBlock] = useState<number>(-1);
	const audioBuffersRef = useRef<Map<number, AudioBufferData>>(new Map());
	const [audioProgress, setAudioProgress] = useState<number>(0);
	const blockStartTimeRef = useRef<number>(0);
	const [actualTotalDuration, setActualTotalDuration] = useState<number>(0);
	const durationCorrectionsRef = useRef<Map<number, number>>(new Map());
	const initialTotalEstimateRef = useRef<number>(0);
  const currentBlockDurationRef = useRef<number>(0);

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

  // Initialize the AudioContext, GainNode, and AudioPlayer
  useEffect(() => {
    // Create new AudioContext if none exists or previous one was closed
    // Use 44100Hz because SoundTouchJS's time-stretch algorithm is hardcoded for 44100Hz
    // Web Audio API will automatically resample our 24000Hz audio
    if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
      audioContextRef.current = new AudioContext({ sampleRate: 44100 });
      gainNodeRef.current = audioContextRef.current.createGain();
      gainNodeRef.current.connect(audioContextRef.current.destination);
      gainNodeRef.current.gain.value = volume / 100;
    }

    // Create AudioPlayer if needed (with pitch-preserving speed control)
    if (!audioPlayerRef.current && audioContextRef.current && gainNodeRef.current) {
      audioPlayerRef.current = new AudioPlayer({
        audioContext: audioContextRef.current,
        gainNode: gainNodeRef.current,
        onProgress: (percentPlayed, blockDurationMs) => {
          // Calculate total progress: previous blocks + current block position
          const blockProgress = (percentPlayed / 100) * blockDurationMs;
          const totalProgress = blockStartTimeRef.current + blockProgress;
          setAudioProgress(totalProgress);
        },
      });
      audioPlayerRef.current.setTempo(playbackSpeed);
    }
  }, [volume, playbackSpeed]);

  // Calculate initial total duration from block estimates
  useEffect(() => {
    if (documentBlocks && documentBlocks.length > 0) {
      let totalEstimate = 0;
      for (const block of documentBlocks) {
        totalEstimate += block.est_duration_ms || 0;
      }
      initialTotalEstimateRef.current = totalEstimate;
      setActualTotalDuration(totalEstimate);
    } else if (estimated_ms) {
      initialTotalEstimateRef.current = estimated_ms;
      setActualTotalDuration(estimated_ms);
    }
  }, [documentBlocks, estimated_ms]);

  // Update gain node value when volume changes
  useEffect(() => {
    if (gainNodeRef.current) {
      gainNodeRef.current.gain.value = volume / 100;
    }
  }, [volume]);

  // Update playback speed in real-time (pitch-preserving)
  useEffect(() => {
    if (audioPlayerRef.current) {
      audioPlayerRef.current.setTempo(playbackSpeed);
    }
  }, [playbackSpeed]);


  const synthesizeBlock = useCallback(async (blockId: number): Promise<AudioBufferData | null> => {
    try {
      const response = await api.post(
        `/v1/documents/${documentId}/blocks/${blockId}/synthesize/models/kokoro-cpu/voices/af_heart`,
        {},
        { responseType: 'arraybuffer' }
      );
      
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
        // Handle raw PCM data - resample to 44100Hz for SoundTouchJS compatibility
        const pcmData = new Int16Array(arrayBuffer);
        const inputFrames = pcmData.length / channels;
        const targetSampleRate = 44100;
        const resampleRatio = targetSampleRate / sampleRate;
        const outputFrames = Math.ceil(inputFrames * resampleRatio);

        audioBuffer = audioContextRef.current.createBuffer(channels, outputFrames, targetSampleRate);

        // Linear interpolation resampling from 24000Hz to 44100Hz
        for (let channel = 0; channel < channels; channel++) {
          const outputData = audioBuffer.getChannelData(channel);
          for (let outFrame = 0; outFrame < outputFrames; outFrame++) {
            const inPos = outFrame / resampleRatio;
            const inFrame = Math.floor(inPos);
            const frac = inPos - inFrame;

            const idx1 = inFrame * channels + channel;
            const idx2 = Math.min(inFrame + 1, inputFrames - 1) * channels + channel;

            const sample1 = pcmData[idx1] / 32768.0;
            const sample2 = pcmData[idx2] / 32768.0;
            outputData[outFrame] = sample1 + frac * (sample2 - sample1);
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
    if (!audioPlayerRef.current) return;

    // Store current block duration for progress calculation
    currentBlockDurationRef.current = audioBufferData.duration_ms;

    // Stop any currently playing audio first
    audioPlayerRef.current.stop();

    // Set up onEnded callback for auto-advance
    audioPlayerRef.current.setOnEnded(() => {
      // Add current block duration to cumulative progress
      blockStartTimeRef.current += currentBlockDurationRef.current;

      setCurrentBlock(prev => {
        if (documentBlocks && prev < documentBlocks.length - 1) {
          return prev + 1;
        } else {
          setIsPlaying(false);
          setAudioProgress(0);
          blockStartTimeRef.current = 0;
          return -1;
        }
      });
    });

    // Load and play the buffer
    audioPlayerRef.current.load(audioBufferData.buffer);
    audioPlayerRef.current.play();
  }, [documentBlocks]);

  // Keep isPlayingRef in sync with state
  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  // Handle block changes and pre-synthesis
  useEffect(() => {
    if (!documentBlocks || currentBlock === -1 || !isPlaying) {
      setIsSynthesizing(false);
      return;
    }

    // Pre-synthesize next block if not the last block
    if (currentBlock < documentBlocks.length - 1) {
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
        setIsSynthesizing(false);
        playAudioBuffer(audioData);
      } else {
        // Show loading state while synthesizing current block
        setIsSynthesizing(true);
        synthesizeBlock(currentBlockId).then(audioData => {
          setIsSynthesizing(false);
          if (audioData && isPlayingRef.current) {
            playAudioBuffer(audioData);
          }
        });
      }
    }
  }, [currentBlock, isPlaying, documentBlocks, playAudioBuffer, synthesizeBlock]);


  const handlePlay = async () => {
    if (isPlaying) return;

    if (audioContextRef.current?.state === 'suspended') {
      await audioContextRef.current.resume();
    }

    setIsPlaying(true);

    if (currentBlock === -1) {
      setCurrentBlock(0);
      setAudioProgress(0);
      blockStartTimeRef.current = 0;
    }
  };

  const handlePause = () => {
    setIsPlaying(false);
    audioPlayerRef.current?.pause();
  };

  const handleSkipBack = () => {
    // Stop current audio
    audioPlayerRef.current?.stop();

    blockStartTimeRef.current = 0;
    setAudioProgress(0);

    if (currentBlock > 0) {
      setCurrentBlock(currentBlock - 1);
    } else if (currentBlock === 0 && isPlaying && documentBlocks.length > 0) {
      // Restart current block - directly play since effect won't re-trigger
      const blockId = documentBlocks[0].id;
      const audioData = audioBuffersRef.current.get(blockId);
      if (audioData) {
        playAudioBuffer(audioData);
      } else {
        synthesizeBlock(blockId).then(data => {
          if (data && isPlayingRef.current) {
            playAudioBuffer(data);
          }
        });
      }
    }
  };

  const handleSkipForward = () => {
    if (documentBlocks && currentBlock < documentBlocks.length - 1) {
      // Stop current audio
      audioPlayerRef.current?.stop();

      // Calculate progress up to the new block
      const newBlock = currentBlock + 1;
      let progressMs = 0;
      for (let i = 0; i < newBlock; i++) {
        const blockData = audioBuffersRef.current.get(documentBlocks[i].id);
        progressMs += blockData?.duration_ms ?? documentBlocks[i].est_duration_ms ?? 0;
      }
      blockStartTimeRef.current = progressMs;
      setAudioProgress(progressMs);
      setCurrentBlock(newBlock);
    }
  };

  const handleBlockChange = (newBlock: number) => {
    if (newBlock === currentBlock) return;
    if (!documentBlocks || newBlock < 0 || newBlock >= documentBlocks.length) return;

    // Stop current audio
    audioPlayerRef.current?.stop();

    // Calculate progress up to the new block
    let progressMs = 0;
    for (let i = 0; i < newBlock; i++) {
      const blockData = audioBuffersRef.current.get(documentBlocks[i].id);
      progressMs += blockData?.duration_ms ?? documentBlocks[i].est_duration_ms ?? 0;
    }
    blockStartTimeRef.current = progressMs;
    setAudioProgress(progressMs);
    setCurrentBlock(newBlock);
  };

  const handleVolumeChange = (newVolume: number) => {
    setVolume(newVolume);
  };

  const handleSpeedChange = (newSpeed: number) => {
    setPlaybackSpeed(newSpeed);
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
    <div className="flex grow pb-32">
      <DocumentCard title={documentTitle} content={documentContent} />
      <SoundControl
        isPlaying={isPlaying}
        isSynthesizing={isSynthesizing}
        onPlay={handlePlay}
        onPause={handlePause}
        onSkipBack={handleSkipBack}
        onSkipForward={handleSkipForward}
        progressBarValues={{
          estimated_ms: actualTotalDuration > 0 ? actualTotalDuration : estimated_ms,
          numberOfBlocks,
          currentBlock: currentBlock >= 0 ? currentBlock : 0,
          setCurrentBlock: handleBlockChange,
          audioProgress,
        }}
        volume={volume}
        onVolumeChange={handleVolumeChange}
        playbackSpeed={playbackSpeed}
        onSpeedChange={handleSpeedChange}
      />
    </div>
  );
};

export default PlaybackPage;