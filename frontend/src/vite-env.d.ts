/// <reference types="vite/client" />

interface ImportMetaEnv {
	readonly VITE_API_BASE_URL: string;
}

// WebGPU type (we only check existence, don't use the full API)
interface Navigator {
	gpu?: GPU;
}

interface GPU {
	requestAdapter(): Promise<GPUAdapter | null>;
}

interface GPUAdapter {
	readonly isFallbackAdapter: boolean;
}
