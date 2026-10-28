import { useAuth } from "@/hooks/useAuthUser";
import axios, { Axios } from "axios";
import {
	createContext,
	FC,
	PropsWithChildren,
	useContext,
	useEffect,
	useMemo,
	useRef,
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

/** The API client. A signed-in browser is authenticated by its session cookie; anyone else by an anonymous session. */
export const ApiProvider: FC<PropsWithChildren> = ({ children }) => {
	const { user, authEnabled, refresh } = useAuth();
	const isAnonymous = authEnabled && user === null;
	const isAnonymousRef = useRef(isAnonymous);
	isAnonymousRef.current = isAnonymous;
	const refreshRef = useRef(refresh);
	refreshRef.current = refresh;
	const claimAttempted = useRef(false);

	const api = useMemo(() => {
		const instance = axios.create({ baseURL });

		instance.interceptors.request.use(async (config) => {
			if (!isAnonymousRef.current) return config;
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

		instance.interceptors.response.use(undefined, async (error) => {
			const config = error.config;
			if (error.response?.status !== 401 || !config) return Promise.reject(error);
			// An anonymous session the gateway no longer accepts: renew it and retry once
			if (config.headers?.["X-Anonymous-ID"] && !config._anonRetried) {
				config._anonRetried = true;
				await renewAnonymousSession();
				config.headers["X-Anonymous-ID"] = await getOrCreateAnonymousId();
				config.headers["X-Anonymous-Token"] = getAnonymousToken();
				return instance.request(config);
			}
			// The session ended (signed out in another tab, expired): find out who we are now
			if (!isAnonymousRef.current) void refreshRef.current();
			return Promise.reject(error);
		});

		return instance;
	}, []);

	// Documents made before signing in move to the account
	useEffect(() => {
		if (!user || !hasAnonymousId() || claimAttempted.current) return;
		claimAttempted.current = true;
		(async () => {
			const anonId = await getOrCreateAnonymousId();
			try {
				await api.post(
					"/v1/users/claim-anonymous",
					{ anonymous_token: getAnonymousToken() },
					{ headers: { "X-Anonymous-ID": anonId } },
				);
				clearAnonymousId();
			} catch (err) {
				console.error("Failed to claim anonymous data:", err);
			}
		})();
	}, [user, api]);

	return (
		<ApiContext.Provider value={{ api, isAuthReady: true, isAnonymous }}>
			{children}
		</ApiContext.Provider>
	);
};

export function useApi(): Api {
	return useContext(ApiContext);
}
