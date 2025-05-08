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
    doc_id: string;
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
    const documentId: string | undefined = apiResponse?.doc_id;
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

// Setup variables
    const audioContextRef = useRef<AudioContext | null>(null);
    const audioWorkletNodeRef = useRef<AudioWorkletNode | null>(null);

// Websocket setup
    const { sendMessage, lastMessage, readyState } = useWebSocket(
        `${wsBaseUrl}${wsUrl}`
    );

    useEffect(() => {
        const initWorklet = async () => {
            if (!audioContextRef.current) return;

            try {
                await audioContextRef.current.audioWorklet.addModule('/pcm-processor.js');
                const workletNode = new AudioWorkletNode(audioContextRef.current, 'pcm-player-processor');
                workletNode.connect(audioContextRef.current.destination);
                audioWorkletNodeRef.current = workletNode;
            } catch (err) {
                console.error("Failed to load AudioWorklet:", err);
            }
        };

        initWorklet();
    }, []);

    useEffect(() => {
        console.log(readyState);
        console.log(lastMessage);
    }, [readyState]);

    useEffect(() => {
        if (!lastMessage || !audioWorkletNodeRef.current) return;

        const processMessage = async () => {
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

            audioWorkletNodeRef.current!.port.postMessage({
                type: 'push',
                audioBuffer: deinterleaved,
            });
        };

        processMessage().catch((err) => {
            console.error('Failed to process PCM audio:', err);
        });

    }, [lastMessage]);

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
        }
    }

    return (
        <div className="w-full">
            <DocumentCard inputText={inputText} />
            <SoundControl isPlaying={isPlaying} onPlay={() => { setIsPlaying(true); synthesizeBlock(documentBlocks![0].id); }} onPause={() => setIsPlaying(false) }/>
        </div>
    )
}

export default PlaybackPage;
