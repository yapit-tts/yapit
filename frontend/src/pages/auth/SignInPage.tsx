import { useEffect, useRef, useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuthUser";
import { ProviderIcon } from "@/components/auth/ProviderIcon";
import { CODE_LENGTH, CodeInput } from "@/components/auth/CodeInput";
import AuthPageLayout from "./AuthPageLayout";
import {
	PROVIDER_NAMES,
	emailSignInLink,
	oauthErrorMessage,
	oauthStartUrl,
	authErrorMessage,
	NOT_AN_EMAIL,
	verifySignIn,
} from "@/lib/authApi";
import { passkeyAutofillAvailable, passkeyErrorMessage, signInWithPasskey } from "@/lib/passkeys";

export default function SignInPage() {
	const { refresh, providers, passkeys } = useAuth();
	const navigate = useNavigate();
	const [searchParams] = useSearchParams();
	const [email, setEmail] = useState("");
	const [sentTo, setSentTo] = useState<string | null>(null);
	const [code, setCode] = useState("");
	const oauthError = searchParams.get("error");
	const [error, setError] = useState<string | null>(oauthError && oauthErrorMessage(oauthError));
	const [busy, setBusy] = useState(false);
	// The autofill request waits in the background; a click on the passkey button replaces it
	const autofill = useRef<AbortController | null>(null);

	const signedIn = async () => {
		await refresh();
		navigate("/", { replace: true });
	};

	useEffect(() => {
		if (!passkeys || sentTo !== null) return;
		const controller = new AbortController();
		autofill.current = controller;
		void (async () => {
			if (!(await passkeyAutofillAvailable()) || controller.signal.aborted) return;
			try {
				await signInWithPasskey({ autofill: true, signal: controller.signal });
				await signedIn();
			} catch (err) {
				if (!controller.signal.aborted) setError(passkeyErrorMessage(err));
			}
		})();
		return () => controller.abort();
		// eslint-disable-next-line react-hooks/exhaustive-deps -- one background request per visit to the email step
	}, [passkeys, sentTo]);

	const onPasskey = async () => {
		autofill.current?.abort();
		setBusy(true);
		setError(null);
		try {
			await signInWithPasskey();
			await signedIn();
		} catch (err) {
			setError(passkeyErrorMessage(err));
			setBusy(false);
		}
	};

	const sendEmail = async (address: string) => {
		setBusy(true);
		setError(null);
		try {
			await emailSignInLink(address);
			setSentTo(address);
			setCode("");
		} catch (err) {
			setError(authErrorMessage(err, NOT_AN_EMAIL));
		} finally {
			setBusy(false);
		}
	};

	const onSubmitEmail = (e: FormEvent) => {
		e.preventDefault();
		void sendEmail(email.trim());
	};

	const submitCode = async (fullCode: string) => {
		if (!sentTo || busy) return;
		setBusy(true);
		setError(null);
		try {
			await verifySignIn({ email: sentTo, code: fullCode });
			await refresh();
			navigate("/", { replace: true });
		} catch (err) {
			setError(authErrorMessage(err));
			setCode("");
			setBusy(false);
		}
	};

	const onSubmitCode = (e: FormEvent) => {
		e.preventDefault();
		void submitCode(code);
	};

	return (
		<AuthPageLayout>
			<Card>
				{sentTo === null ? (
					<>
						<CardHeader>
							<CardTitle className="text-2xl">Sign in or sign up</CardTitle>
						</CardHeader>
						<CardContent className="flex flex-col gap-4">
							{(providers.length > 0 || passkeys) && (
								<>
									<div className="flex flex-col gap-2">
										{passkeys && (
											<Button variant="outline" onClick={() => void onPasskey()} disabled={busy}>
												<KeyRound className="h-4 w-4" />
												Sign in with a passkey
											</Button>
										)}
										{providers.map((provider) => (
											<Button key={provider} variant="outline" asChild>
												<a href={oauthStartUrl(provider, "sign_in", "/")}>
													<ProviderIcon provider={provider} className="h-4 w-4" />
													Continue with {PROVIDER_NAMES[provider]}
												</a>
											</Button>
										))}
									</div>
									<div className="flex items-center gap-3 text-xs text-muted-foreground">
										<div className="h-px flex-1 bg-border" />
										or
										<div className="h-px flex-1 bg-border" />
									</div>
								</>
							)}
							<form onSubmit={onSubmitEmail} className="flex flex-col gap-4">
								<div className="flex flex-col gap-2">
									<Label htmlFor="email">Email</Label>
									<Input
										id="email"
										type="email"
										autoComplete={passkeys ? "email webauthn" : "email"}
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
								<div className="flex justify-center">
									<CodeInput
										value={code}
										onChange={setCode}
										onComplete={(fullCode) => void submitCode(fullCode)}
										disabled={busy}
									/>
								</div>
								{error && <p className="text-sm text-destructive">{error}</p>}
								<Button type="submit" disabled={busy || code.length < CODE_LENGTH}>
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
