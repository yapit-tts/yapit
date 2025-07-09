import { useUser } from "@stackframe/react";
import axios, { Axios } from "axios";
import {
	createContext,
	FC,
	PropsWithChildren,
	useContext,
	useEffect,
	useRef,
} from "react";

const baseURL = "http://localhost:8000"; // TODO: read from env vars

export type Api = {
	api: Axios;
};

const ApiContext = createContext<Api>({
	api: axios.create({ baseURL }),
});

export const ApiProvider: FC<PropsWithChildren<{}>> = ({ children }) => {
	const ref = useRef<Axios>(axios.create({ baseURL }));

	const user = useUser();

	const updateToken = (token: string | undefined): void => {
		ref.current = axios.create({
			baseURL,
			headers: token
				? {
						Authorization: `Bearer ${token}`,
					}
				: undefined,
		});
	};

	useEffect(() => {
		if (!user?.currentSession) {
			updateToken(undefined);
			return;
		}

		user.currentSession
			.getTokens()
			.then(({ accessToken }) => updateToken(accessToken || undefined))
			.catch((err) =>
				console.error("api provider: failed to get access token:", err),
			);
	}, [user?.currentSession]);

	return (
		<ApiContext.Provider value={{ api: ref.current }}>
			{children}
		</ApiContext.Provider>
	);
};

export function useApi(): Api {
	return useContext(ApiContext);
}
