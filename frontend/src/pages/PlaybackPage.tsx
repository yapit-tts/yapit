import { SoundControl } from '@/components/soundControl';
import { DocumentCard } from '../components/documentCard';
import { useWS } from '@/hooks/useWS';
import { useLocation } from "react-router";
import { useRef, useState, useEffect } from "react";
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
  const { state } = useLocation();
  const apiResponse: ApiResponse | undefined = state?.apiResponse;
	const documentId: string | undefined = apiResponse?.document_id;
  const documentBlocks: Block[] | undefined = apiResponse?.blocks;
  const inputText: string | undefined = state?.inputText;

  const [sampleRate, setSampleRate] = useState<number>(0);
	const [channels, setChannels] = useState<number>(0);
	const [bitsPerSample, setBitsPerSample] = useState<number>(0);
	const [wsUrl, setWsUrl] = useState<string>("");
	const { lastMessage, readyState, sendMessage } = useWS(wsUrl);

	const [isPlaying, setIsPlaying] = useState<boolean>(false);

  const synthesizeBlock = async (blockId: number) => {
    try {
      const response = await api.post(`/v1/documents/${documentId}/blocks/${blockId}/synthesize`, {
        "model_slug": "kokoro",
        "voice_slug": "af_heart",
        "speed": 1,
      });
			const data: SynthesizeBlockResponse = response.data;
     
			setSampleRate(data.sample_rate);
			setChannels(data.channels);
			setBitsPerSample(data.sample_width * 8); // convert number of bytes to bits
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
