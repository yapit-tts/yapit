import { useAuthUser } from "@/hooks/useAuthUser";
import { authEnabled } from "@/auth";
import axios, { Axios } from "axios";
import {
	createContext,
	FC,
	PropsWithChildren,
	useContext,
	useEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import {
	clearAnonymousId,
	getAnonymousToken,
	getOrCreateAnonymousId,
	hasAnonymousId,
	renewAnonymousSession,
} from "./lib/anonymousId";

const baseURL = import.meta.env.VITE_API_BASE_URL;

export type Api = {
	api: Axios;
	isAuthReady: boolean;
	isAnonymous: boolean;
};

const ApiContext = createContext<Api>({
	api: axios.create({ baseURL }),
	isAuthReady: false,
	isAnonymous: true,
});

export const ApiProvider: FC<PropsWithChildren> = ({ children }) => {
	const userRef = useRef<typeof user>(undefined);
	const [isAuthReady, setIsAuthReady] = useState(!authEnabled);
	const [isAnonymous, setIsAnonymous] = useState(authEnabled);
	const [authTrigger, setAuthTrigger] = useState(0);
	const claimAttempted = useRef(false);
	const user = useAuthUser();

	// Keep userRef in sync with current user
	useEffect(() => {
		userRef.current = user;
	}, [user]);

	// Re-trigger auth resolution on network recovery / tab focus
	useEffect(() => {
		const bump = () => setAuthTrigger((c) => c + 1);
		const onVisible = () => {
			if (document.visibilityState === "visible") bump();
		};
		window.addEventListener("online", bump);
		document.addEventListener("visibilitychange", onVisible);
		return () => {
			window.removeEventListener("online", bump);
			document.removeEventListener("visibilitychange", onVisible);
		};
	}, []);

	// Create axios instance once with interceptor that fetches fresh token per request
	const api = useMemo(() => {
		const instance = axios.create({ baseURL });

		instance.interceptors.request.use(async (config) => {
			if (!authEnabled) return config;

			const currentUser = userRef.current;

			if (currentUser?.currentSession) {
				// Fetch fresh token for each request (handles expiry/refresh automatically)
				try {
					const { accessToken } = await currentUser.currentSession.getTokens();
					if (accessToken) {
						config.headers.Authorization = `Bearer ${accessToken}`;
						return config;
					}
				} catch (err) {
					console.error("api: failed to get access token:", err);
				}
			}

			// Anonymous user or token fetch failed - send anonymous ID + HMAC token
			config.headers["X-Anonymous-ID"] = await getOrCreateAnonymousId();
			config.headers["X-Anonymous-Token"] = getAnonymousToken();
			return config;
		});

		instance.interceptors.response.use(undefined, (error) => {
			if (error.response?.status >= 500) {
				console.error(`[api] ${error.response.status} ${error.config?.method?.toUpperCase()} ${error.config?.url}`);
			}
			return Promise.reject(error);
		});

		// On 401 for anonymous users, renew session and retry once
		instance.interceptors.response.use(undefined, async (error) => {
			const config = error.config;
			if (
				error.response?.status === 401 &&
				config?.headers?.["X-Anonymous-ID"] &&
				!config._anonRetried
			) {
				config._anonRetried = true;
				await renewAnonymousSession();
				config.headers["X-Anonymous-ID"] = await getOrCreateAnonymousId();
				config.headers["X-Anonymous-Token"] = getAnonymousToken();
				return instance.request(config);
			}
			return Promise.reject(error);
		});

		return instance;
	}, []);

	useEffect(() => {
		if (!authEnabled) return;
		if (user === undefined) return;

		if (user === null || !user.currentSession) {
			setIsAnonymous(true);
			setIsAuthReady(true);
			return;
		}

		let cancelled = false;
		const MAX_RETRIES = 3;

		async function resolveAuth(attempt = 0) {
			try {
				const { accessToken } =
					await user!.currentSession!.getTokens();
				if (cancelled) return;
				setIsAnonymous(!accessToken);
				setIsAuthReady(true);

				if (
					accessToken &&
					hasAnonymousId() &&
					!claimAttempted.current
				) {
					claimAttempted.current = true;
					const anonId = await getOrCreateAnonymousId();
					const anonToken = getAnonymousToken();
					try {
						await api.post(
							"/v1/users/claim-anonymous",
							{ anonymous_token: anonToken },
							{ headers: { "X-Anonymous-ID": anonId } },
						);
						clearAnonymousId();
					} catch (err) {
						console.error("Failed to claim anonymous data:", err);
					}
				}
			} catch (err) {
				if (cancelled) return;
				if (attempt < MAX_RETRIES) {
					await new Promise((r) =>
						setTimeout(r, 1000 * 2 ** attempt),
					);
					if (!cancelled) return resolveAuth(attempt + 1);
				}
				console.error(
					`api provider: failed to get access token after ${attempt + 1} attempts:`,
					err,
				);
				setIsAnonymous(true);
				setIsAuthReady(true);
			}
		}

		resolveAuth();
		return () => {
			cancelled = true;
		};
	}, [user, api, authTrigger]);

	return (
		<ApiContext.Provider value={{ api, isAuthReady, isAnonymous }}>
			{children}
		</ApiContext.Provider>
	);
};

export function useApi(): Api {
	return useContext(ApiContext);
}
