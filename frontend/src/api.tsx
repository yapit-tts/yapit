import { useUser } from "@stackframe/react";
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
import { getOrCreateAnonymousId } from "./lib/anonymousId";

const baseURL = "http://localhost:8000"; // TODO: read from env vars

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

export const ApiProvider: FC<PropsWithChildren<{}>> = ({ children }) => {
	const tokenRef = useRef<string | undefined>(undefined);
	const [isAuthReady, setIsAuthReady] = useState(false);
	const [isAnonymous, setIsAnonymous] = useState(true);
	const user = useUser();

	// Create axios instance once with interceptor that reads current token
	const api = useMemo(() => {
		const instance = axios.create({ baseURL });

		instance.interceptors.request.use((config) => {
			if (tokenRef.current) {
				config.headers.Authorization = `Bearer ${tokenRef.current}`;
			} else {
				// Anonymous user - send anonymous ID for session tracking
				config.headers["X-Anonymous-ID"] = getOrCreateAnonymousId();
			}
			return config;
		});

		return instance;
	}, []);

	useEffect(() => {
		// user === undefined means Stack Auth is still loading
		// user === null means user is not logged in (auth resolved, no user)
		// user object present means user is logged in
		if (user === undefined) {
			// Still loading, don't set isAuthReady yet
			return;
		}

		if (user === null || !user.currentSession) {
			// No user or no session - anonymous mode
			tokenRef.current = undefined;
			setIsAnonymous(true);
			setIsAuthReady(true);
			return;
		}

		// User is logged in, get the token
		user.currentSession
			.getTokens()
			.then(({ accessToken }) => {
				tokenRef.current = accessToken || undefined;
				setIsAnonymous(!accessToken);
				setIsAuthReady(true);
			})
			.catch((err) => {
				console.error("api provider: failed to get access token:", err);
				setIsAnonymous(true);
				setIsAuthReady(true);
			});
	}, [user]);

	return (
		<ApiContext.Provider value={{ api, isAuthReady, isAnonymous }}>
			{children}
		</ApiContext.Provider>
	);
};

export function useApi(): Api {
	return useContext(ApiContext);
}
