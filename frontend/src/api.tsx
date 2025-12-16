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

const baseURL = "http://localhost:8000"; // TODO: read from env vars

export type Api = {
	api: Axios;
	isAuthReady: boolean;
};

const ApiContext = createContext<Api>({
	api: axios.create({ baseURL }),
	isAuthReady: false,
});

export const ApiProvider: FC<PropsWithChildren<{}>> = ({ children }) => {
	const tokenRef = useRef<string | undefined>(undefined);
	const [isAuthReady, setIsAuthReady] = useState(false);
	const user = useUser();

	// Create axios instance once with interceptor that reads current token
	const api = useMemo(() => {
		const instance = axios.create({ baseURL });

		instance.interceptors.request.use((config) => {
			if (tokenRef.current) {
				config.headers.Authorization = `Bearer ${tokenRef.current}`;
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
			// No user or no session - proceed without auth
			tokenRef.current = undefined;
			setIsAuthReady(true);
			return;
		}

		// User is logged in, get the token
		user.currentSession
			.getTokens()
			.then(({ accessToken }) => {
				tokenRef.current = accessToken || undefined;
				setIsAuthReady(true);
			})
			.catch((err) => {
				console.error("api provider: failed to get access token:", err);
				setIsAuthReady(true);
			});
	}, [user]);

	return (
		<ApiContext.Provider value={{ api, isAuthReady }}>
			{children}
		</ApiContext.Provider>
	);
};

export function useApi(): Api {
	return useContext(ApiContext);
}
