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
	const [isAuthReady, setIsAuthReady] = useState(false);
	const [isAnonymous, setIsAnonymous] = useState(true);
	const user = useUser();

	// Keep userRef in sync with current user
	useEffect(() => {
		userRef.current = user;
	}, [user]);

	// Create axios instance once with interceptor that fetches fresh token per request
	const api = useMemo(() => {
		const instance = axios.create({ baseURL });

		instance.interceptors.request.use(async (config) => {
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

			// Anonymous user or token fetch failed - send anonymous ID
			config.headers["X-Anonymous-ID"] = getOrCreateAnonymousId();
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
			setIsAnonymous(true);
			setIsAuthReady(true);
			return;
		}

		// User is logged in - verify we can get a token
		user.currentSession
			.getTokens()
			.then(({ accessToken }) => {
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
