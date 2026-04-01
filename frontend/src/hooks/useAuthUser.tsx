import { createContext, useContext, type FC, type PropsWithChildren } from "react";
import { useUser } from "@stackframe/react";

type AuthUser = ReturnType<typeof useUser>;

const AuthUserContext = createContext<AuthUser>(null);

/** Sits inside StackProvider — bridges Stack Auth user into our context. */
export const StackAuthBridge: FC<PropsWithChildren> = ({ children }) => {
	const user = useUser();
	return (
		<AuthUserContext.Provider value={user}>
			{children}
		</AuthUserContext.Provider>
	);
};

/** Provides null user when auth is disabled. */
export const NoAuthBridge: FC<PropsWithChildren> = ({ children }) => {
	return (
		<AuthUserContext.Provider value={null}>
			{children}
		</AuthUserContext.Provider>
	);
};

export function useAuthUser(): AuthUser {
	return useContext(AuthUserContext);
}
