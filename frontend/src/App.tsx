import './App.css';
import { Header } from "@/components/header";
import { Navbar } from "@/components/navbar";
import { DocumentUpload } from "@/components/documentUpload";
import { SoundControl } from './components/soundControl';

function App() {

  return (
    <>
			<Navbar />
      <Header />
			<DocumentUpload />
			<SoundControl />
    </>
  )
}

export default App
