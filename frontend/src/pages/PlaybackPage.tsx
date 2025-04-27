import { SoundControl } from '@/components/soundControl';
import { DocumentCard } from '../components/documentCard';
import { useWS } from '@/hooks/useWS';
import { useLocation } from "react-router";
import { useRef, useState, useEffect } from "react";

const PlaybackPage = () => {
	const { state } = useLocation();
  const apiResponse = state?.apiResponse;
	const inputText = state?.inputText;
	const audioChunks = useRef<ArrayBuffer[]>([]);
  const audioContext = useRef<AudioContext | null>(null);
  const sourceNode = useRef<AudioBufferSourceNode | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  const { sendJsonMessage, lastMessage } = useWS(apiResponse.ws_url, {
    onMessage: (event) => handleAudioData(event.data as ArrayBuffer)
  });

  const handleAudioData = async (chunk: ArrayBuffer) => {
    audioChunks.current.push(chunk);
    if (!audioContext.current) {
      audioContext.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    processAudioQueue();
  };

  const processAudioQueue = async () => {
    while (audioChunks.current.length > 0 && isPlaying) {
      const chunk = audioChunks.current.shift()!;
      const audioBuffer = await audioContext.current!.decodeAudioData(chunk);
      
      sourceNode.current = audioContext.current!.createBufferSource();
      sourceNode.current.buffer = audioBuffer;
      sourceNode.current.connect(audioContext.current!.destination);
      sourceNode.current.start(0);
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      sourceNode.current?.disconnect();
      audioContext.current?.close();
    };
  }, []);

	return (
		<div className="w-full">
			<DocumentCard inputText={inputText} />
			<SoundControl isPlaying={isPlaying} onPlay={() => { setIsPlaying(true); audioContext.current?.resume(); processAudioQueue(); }} onPause={() => setIsPlaying(false)} />
		</div>
	)
}

export default PlaybackPage;
