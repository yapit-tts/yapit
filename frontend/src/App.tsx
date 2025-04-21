import './App.css';
import { Header } from "@/components/header";
import { Navbar } from "@/components/navbar";
import { DocumentUpload } from "@/components/documentUpload";

function App() {

  return (
    <>
			<Navbar />
      <Header />
			<DocumentUpload />
    </>
  )
}

export default App
