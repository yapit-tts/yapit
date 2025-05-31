// TODO: remove me

import { useUser } from "@stackframe/react";
import { useEffect, useState } from "react";

export const AuthTest = () => {
	const user = useUser();

	const [token, setToken] = useState("");

	useEffect(() => {
		if (!user) {
			console.error("User is not authenticated");
			return;
		}

		user.currentSession
			.getTokens()
			.then((t) => {
				setToken(t.accessToken || "");
			})
			.catch((err) => console.error("Error fetching tokens:", err));
	}, [user]);

	return (
		<>
			<div>User Token: {token}</div>
		</>
	);
};
