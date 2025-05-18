import { SoundControl } from '@/components/soundControl';
import { DocumentCard } from '../components/documentCard';
import { useLocation } from "react-router";
import { useRef, useState, useEffect } from "react";
import useWebSocket from 'react-use-websocket';
import api from "@/api";

interface Block {
  id: number;
  idx: number;
  text: string;
  est_duration_ms: number;
}

interface ApiResponse {
  document_id: string;
  num_blocks: number;
  est_duration_ms: number;
  blocks: Block[];
}

interface SynthesizeBlockResponse {
  variant_hash: string;
  ws_url: string;
  codec: string;
  sample_rate: number;
  channels: number;
  sample_width: number;
  est_ms?: number;
  duration_ms?: number;
}

const PlaybackPage = () => {
  // State variables
  const { state } = useLocation();
  const apiResponse: ApiResponse | undefined = state?.apiResponse;
  const documentId: string | undefined = apiResponse?.document_id;
	const numberOfBlocks: number | undefined = apiResponse?.num_blocks;
  const documentBlocks: Block[] | undefined = apiResponse?.blocks;
  const inputText: string | undefined = state?.inputText;

  // Env variables
  const wsBaseUrl: string = import.meta.env.VITE_WS_BASE_URL || "http://localhost:8000";

  // Api response variables
  const sampleRate = useRef<number>(0);
  const channels = useRef<number>(0);
  const bitsPerSample = useRef<number>(0);
  const [wsUrl, setWsUrl] = useState<string>("");

  // Sound control variables
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [isReady, setIsReady] = useState<boolean>(false);
	const parentWidth = useRef<HTMLElement>(null);
	const [width, setWidth] = useState(0);

  // Setup variables
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioWorkletNodeRef = useRef<AudioWorkletNode | null>(null);
	const [currentBlock, setCurrentBlock] = useState<number>(0);

  // Websocket setup - only connect when wsUrl is available
  const { lastMessage, readyState } = useWebSocket(
    wsUrl ? `${wsBaseUrl}${wsUrl}` : null,
    {
      onOpen: () => {
        console.log('WebSocket connection established');
      },
      onError: (event) => {
        console.error('WebSocket error:', event);
        setIsPlaying(false);
      },
      onClose: () => {
        console.log('WebSocket connection closed');
      },
    }
  );

  // Initialize the AudioReact.CSSPropertiest
  useEffect(() => {
    const initWorklet = async () => {
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext({ sampleRate: 24000 });

				try {
					await audioContextRef.current.audioWorklet.addModule('/pcm-processor.js');
					const workletNode = new AudioWorkletNode(audioContextRef.current, 'pcm-processor');
					workletNode.connect(audioContextRef.current.destination);
					audioWorkletNodeRef.current = workletNode;
					setIsReady(true);
					console.log("AudioWorklet initialized successfully");
				} catch (err) {
					console.error("Failed to load AudioWorklet:", err);
				}
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

  // Process incoming WebSocket messages
  useEffect(() => {
    if (!lastMessage || !audioWorkletNodeRef.current) return;

    const processMessage = async () => {
      try {
        const arrayBuffer = lastMessage.data instanceof Blob
          ? await lastMessage.data.arrayBuffer()
          : lastMessage.data;

        const int16 = new Int16Array(arrayBuffer);
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) {
          float32[i] = int16[i] / 32768;
        }

        const channelCount = channels.current || 1;
        const frameCount = float32.length / channelCount;

        const deinterleaved = Array.from({ length: channelCount }, (_, c) => new Float32Array(frameCount));
        for (let i = 0; i < frameCount; i++) {
          for (let c = 0; c < channelCount; c++) {
            deinterleaved[c][i] = float32[i * channelCount + c];
          }
        }

				const rawBuffer = float32.buffer;
        audioWorkletNodeRef.current!.port.postMessage(rawBuffer, [rawBuffer]);
      } catch (err) {
        console.error('Failed to process PCM audio:', err);
      }
    };

    processMessage();
  }, [lastMessage]);

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

	useEffect(() => {
		if (readyState == 3) synthesizeBlock(documentBlocks[currentBlock + 1].id);
		console.log(readyState);
	}, [currentBlock, readyState])

  const synthesizeBlock = async (blockId: number) => {
    try {
      const response = await api.post(`/v1/documents/${documentId}/blocks/${blockId}/synthesize`, {
        "model_slug": "kokoro",
        "voice_slug": "af_heart",
        "speed": 1,
      });
      const data: SynthesizeBlockResponse = response.data;

      sampleRate.current = data.sample_rate;
      channels.current = data.channels;
      bitsPerSample.current = data.sample_width * 8; // convert number of bytes to bits
      
      setWsUrl(data.ws_url);

    } catch (error) {
      console.error("Error synthesizing block: ", error);
      setIsPlaying(false);
    }
  };

  const handlePlay = async () => {
    setIsPlaying(true);
		if (currentBlock == 0) {
			await synthesizeBlock(documentBlocks[0].id);
		}
  };

  const handlePause = () => {
    setIsPlaying(false);
    setWsUrl(""); 
  };

  return (
    <div className="flex grow" ref={parentWidth}>
      <DocumentCard inputText={inputText} />
      <SoundControl 
        isPlaying={isPlaying} 
        onPlay={handlePlay} 
        onPause={handlePause}
				style={{ width: `${width}px` }}
      />
      {!isReady && <div>Initializing audio system...</div>}
    </div>
  );
};

export default PlaybackPage;
