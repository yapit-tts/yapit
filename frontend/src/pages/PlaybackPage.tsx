import { SoundControl } from '@/components/soundControl';
import { DocumentCard } from '../components/documentCard';

const PlaybackPage = () => {
	return (
		<div className="w-full">
			<DocumentCard />
			<SoundControl />
		</div>
	)
}

export default PlaybackPage;
