import { Routes, Route } from "react-router";
import MainLayout from "../layouts/MainLayout";
import PlaybackPage from "../pages/PlaybackPage";
import TextInputPage from "@/pages/TextInputPage";

const AppRoutes = () => (
	<Routes>
		<Route path="/input" element={<MainLayout><TextInputPage /></MainLayout>}/>
		<Route path="/playback" element={<MainLayout><PlaybackPage /></MainLayout>} />
	</Routes>
);

export default AppRoutes;
