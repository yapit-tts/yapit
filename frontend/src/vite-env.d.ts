/// <reference types="vite/client" />

interface ImportMetaEnv {
	readonly VITE_STACK_AUTH_PROJECT_ID: string;
	readonly VITE_STACK_AUTH_CLIENT_KEY: string;
	readonly VITE_STACK_BASE_URL: string;
}

// WebGPU type (we only check existence, don't use the full API)
interface Navigator {
	gpu?: GPU;
}

interface GPU {
	requestAdapter(): Promise<GPUAdapter | null>;
}

interface GPUAdapter {}
