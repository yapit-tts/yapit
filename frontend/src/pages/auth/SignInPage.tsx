import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuthUser";
import AuthPageLayout from "./AuthPageLayout";
import { emailSignInLink, signInError, verifySignIn } from "./signInApi";

export default function SignInPage() {
	const { refresh } = useAuth();
	const navigate = useNavigate();
	const [email, setEmail] = useState("");
	const [sentTo, setSentTo] = useState<string | null>(null);
	const [code, setCode] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);

	const sendEmail = async (address: string) => {
		setBusy(true);
		setError(null);
		try {
			await emailSignInLink(address);
			setSentTo(address);
			setCode("");
		} catch (err) {
			setError(signInError(err));
		} finally {
			setBusy(false);
		}
	};

	const onSubmitEmail = (e: FormEvent) => {
		e.preventDefault();
		void sendEmail(email.trim());
	};

	const onSubmitCode = async (e: FormEvent) => {
		e.preventDefault();
		if (!sentTo) return;
		setBusy(true);
		setError(null);
		try {
			await verifySignIn({ email: sentTo, code: code.trim() });
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
				{sentTo === null ? (
					<>
						<CardHeader>
							<CardTitle className="text-2xl">Sign in to Yapit</CardTitle>
							<CardDescription>
								We'll email you a link and a code. No password needed, and a new address gets a new account.
							</CardDescription>
						</CardHeader>
						<CardContent>
							<form onSubmit={onSubmitEmail} className="flex flex-col gap-4">
								<div className="flex flex-col gap-2">
									<Label htmlFor="email">Email</Label>
									<Input
										id="email"
										type="email"
										autoComplete="email"
										autoFocus
										required
										value={email}
										onChange={(e) => setEmail(e.target.value)}
									/>
								</div>
								{error && <p className="text-sm text-destructive">{error}</p>}
								<Button type="submit" disabled={busy}>
									Email me a sign-in link
								</Button>
							</form>
						</CardContent>
					</>
				) : (
					<>
						<CardHeader>
							<CardTitle className="text-2xl">Check your email</CardTitle>
							<CardDescription>
								We sent a sign-in link and a 6-digit code to <strong>{sentTo}</strong>. Open the link, or enter
								the code here.
							</CardDescription>
						</CardHeader>
						<CardContent>
							<form onSubmit={onSubmitCode} className="flex flex-col gap-4">
								<div className="flex flex-col gap-2">
									<Label htmlFor="code">Code</Label>
									<Input
										id="code"
										inputMode="numeric"
										autoComplete="one-time-code"
										pattern="[0-9]{6}"
										maxLength={6}
										autoFocus
										required
										value={code}
										onChange={(e) => setCode(e.target.value)}
									/>
								</div>
								{error && <p className="text-sm text-destructive">{error}</p>}
								<Button type="submit" disabled={busy}>
									Sign in
								</Button>
								<div className="flex justify-between text-sm text-muted-foreground">
									<button type="button" className="hover:text-foreground underline" onClick={() => void sendEmail(sentTo)} disabled={busy}>
										Send a new email
									</button>
									<button type="button" className="hover:text-foreground underline" onClick={() => { setSentTo(null); setError(null); }}>
										Use a different email
									</button>
								</div>
							</form>
						</CardContent>
					</>
				)}
			</Card>
		</AuthPageLayout>
	);
}
