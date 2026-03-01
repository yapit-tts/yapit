import { Component, type ReactNode, type ErrorInfo } from "react";

interface Props {
	children: ReactNode;
}

interface State {
	error: Error | null;
}

function isChunkLoadError(error: Error): boolean {
	return (
		error.name === "ChunkLoadError" ||
		error.message.includes("Failed to fetch dynamically imported module") ||
		error.message.includes("Importing a module script failed")
	);
}

export class ChunkErrorBoundary extends Component<Props, State> {
	state: State = { error: null };

	static getDerivedStateFromError(error: Error): State {
		return { error };
	}

	componentDidCatch(error: Error, info: ErrorInfo) {
		if (isChunkLoadError(error)) {
			window.location.reload();
			return;
		}
		console.error("Route error:", error, info);
	}

	render() {
		if (this.state.error && !isChunkLoadError(this.state.error)) {
			return (
				<div className="flex flex-col items-center justify-center min-h-[50vh] gap-4">
					<p className="text-muted-foreground">Something went wrong.</p>
					<button
						onClick={() => window.location.reload()}
						className="text-sm underline text-muted-foreground hover:text-foreground"
					>
						Reload page
					</button>
				</div>
			);
		}
		return this.props.children;
	}
}
