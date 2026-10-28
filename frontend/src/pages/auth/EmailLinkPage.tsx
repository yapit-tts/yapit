import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuthUser";
import AuthPageLayout from "./AuthPageLayout";
import { signInError, verifySignIn } from "./signInApi";

/** Where a sign-in email's link lands. Signing in waits for a click, so a mail scanner opening the link uses nothing up. */
export default function EmailLinkPage() {
	const [params] = useSearchParams();
	const token = params.get("token");
	const email = params.get("email");
	const { refresh } = useAuth();
	const navigate = useNavigate();
	const [error, setError] = useState<string | null>(token ? null : "This sign-in link is incomplete.");
	const [busy, setBusy] = useState(false);

	const signIn = async () => {
		if (!token) return;
		setBusy(true);
		setError(null);
		try {
			await verifySignIn({ token });
			await refresh();
			navigate("/", { replace: true });
		} catch (err) {
			setError(signInError(err));
			setBusy(false);
		}
	};

	return (
		<AuthPageLayout>
			<Card>
				<CardHeader>
					<CardTitle className="text-2xl">Sign in to Yapit</CardTitle>
					{email && <CardDescription>as {email}</CardDescription>}
				</CardHeader>
				<CardContent className="flex flex-col gap-4">
					{error ? (
						<>
							<p className="text-sm text-destructive">{error}</p>
							<Button asChild variant="outline">
								<Link to="/auth/sign-in">Get a new sign-in email</Link>
							</Button>
						</>
					) : (
						<Button onClick={() => void signIn()} disabled={busy} autoFocus>
							{email ? `Continue as ${email}` : "Continue"}
						</Button>
					)}
				</CardContent>
			</Card>
		</AuthPageLayout>
	);
}
