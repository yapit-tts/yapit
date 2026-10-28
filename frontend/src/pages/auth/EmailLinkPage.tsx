import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuthUser";
import { isOtherBrowser, signInError, verifySignIn } from "@/lib/authApi";
import AuthPageLayout from "./AuthPageLayout";

/** The link's token and email, which travel in the fragment so no server or proxy log ever sees them. */
function readLink(): { token: string | null; email: string | null } {
	const params = new URLSearchParams(window.location.hash.slice(1));
	return { token: params.get("token"), email: params.get("email") };
}

/**
 * Where a sign-in email's link lands. In the browser that asked for the link it signs in at once;
 * anywhere else (a mail scanner opening every link, another device) it waits for a click, so
 * opening the link uses nothing up.
 */
export default function EmailLinkPage() {
	const [{ token, email }] = useState(readLink);
	const { refresh } = useAuth();
	const navigate = useNavigate();
	const [state, setState] = useState<"trying" | "confirm" | "busy" | "error">(token ? "trying" : "error");
	const [error, setError] = useState<string | null>(token ? null : "This sign-in link is incomplete.");
	const tried = useRef(false);

	const signIn = async (sameBrowserOnly: boolean) => {
		if (!token) return;
		try {
			await verifySignIn({ token, same_browser_only: sameBrowserOnly });
			await refresh();
			navigate("/", { replace: true });
		} catch (err) {
			if (sameBrowserOnly && isOtherBrowser(err)) {
				setState("confirm");
				return;
			}
			setError(signInError(err));
			setState("error");
		}
	};

	useEffect(() => {
		if (tried.current) return;
		tried.current = true;
		// Keep the token out of the browser history
		window.history.replaceState(window.history.state, "", window.location.pathname);
		if (token) void signIn(true);
	});

	return (
		<AuthPageLayout>
			<Card>
				<CardHeader>
					<CardTitle className="text-2xl">Sign in to Yapit</CardTitle>
					{email && <CardDescription>as {email}</CardDescription>}
				</CardHeader>
				<CardContent className="flex flex-col gap-4">
					{state === "trying" && <Loader2 className="h-6 w-6 animate-spin text-muted-foreground mx-auto" />}
					{(state === "confirm" || state === "busy") && (
						<Button
							onClick={() => {
								setState("busy");
								void signIn(false);
							}}
							disabled={state === "busy"}
							autoFocus
						>
							{email ? `Continue as ${email}` : "Continue"}
						</Button>
					)}
					{state === "error" && (
						<>
							<p className="text-sm text-destructive">{error}</p>
							<Button asChild variant="outline">
								<Link to="/auth/sign-in">Get a new sign-in email</Link>
							</Button>
						</>
					)}
				</CardContent>
			</Card>
		</AuthPageLayout>
	);
}
