import {
	createContext,
	useCallback,
	useContext,
	useEffect,
	useState,
	type FC,
	type PropsWithChildren,
} from "react";
import {
	fetchSession,
	signOut as requestSignOut,
	type AuthUser,
	type OAuthProvider,
	type SessionState,
} from "@/lib/authApi";

export type { AuthUser };

export interface Auth {
	user: AuthUser | null;
	authEnabled: boolean;
	providers: OAuthProvider[];
	signOut: () => Promise<void>;
	/** Re-reads who the session cookie belongs to, e.g. after signing in. */
	refresh: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

/** Renders its children once the gateway has said who is signed in. */
export const AuthProvider: FC<PropsWithChildren> = ({ children }) => {
	const [session, setSession] = useState<SessionState | null>(null);
	const [unreachable, setUnreachable] = useState(false);

	const load = useCallback(async () => {
		const MAX_ATTEMPTS = 4;
		for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
			try {
				setSession(await fetchSession());
				setUnreachable(false);
				return;
			} catch (err) {
				if (attempt === MAX_ATTEMPTS - 1) {
					console.error("[auth] could not load the session:", err);
					setUnreachable(true);
					return;
				}
				await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
			}
		}
	}, []);

	useEffect(() => {
		void load();
	}, [load]);

	const refresh = useCallback(async () => {
		try {
			setSession(await fetchSession());
		} catch (err) {
			console.error("[auth] could not refresh the session:", err);
		}
	}, []);

	const signOut = useCallback(async () => {
		await requestSignOut();
		await refresh();
	}, [refresh]);

	if (session === null) {
		if (!unreachable) return null;
		return (
			<div className="p-8">
				<h2 className="text-xl font-semibold mb-2">Yapit's server is not reachable</h2>
				<p className="text-muted-foreground mb-4">Check your connection, then try again.</p>
				<button className="underline" onClick={() => void load()}>
					Try again
				</button>
			</div>
		);
	}

	return (
		<AuthContext.Provider
			value={{
				user: session.user,
				authEnabled: session.auth_enabled,
				providers: session.providers,
				signOut,
				refresh,
			}}
		>
			{children}
		</AuthContext.Provider>
	);
};

export function useAuth(): Auth {
	const auth = useContext(AuthContext);
	if (auth === null) throw new Error("useAuth needs an AuthProvider above it");
	return auth;
}

export function useAuthUser(): AuthUser | null {
	return useAuth().user;
}
