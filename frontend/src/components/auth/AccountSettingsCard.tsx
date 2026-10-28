import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { Check, Copy, KeyRound, Mail } from "lucide-react";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SectionHeading, SettingRow } from "@/components/settingsDialog";
import { ProviderIcon } from "@/components/auth/ProviderIcon";
import { useAuth, type AuthUser } from "@/hooks/useAuthUser";
import {
	PROVIDER_NAMES,
	oauthErrorMessage,
	oauthStartUrl,
	authErrorMessage,
	NOT_AN_EMAIL,
	verifySignIn,
	type OAuthProvider,
} from "@/lib/authApi";

const RETURN_TO = "/account";

/** Name, email, the ways to sign in, and API tokens. */
export function AccountSettingsCard() {
	const { user } = useAuth();
	if (!user) return null;
	return (
		<Card className="mb-10">
			<CardHeader>
				<CardTitle className="text-base">Account</CardTitle>
			</CardHeader>
			<CardContent>
				<SectionHeading first>Profile</SectionHeading>
				<div className="flex flex-col">
					<NameRow user={user} />
					<EmailRow user={user} />
				</div>
				<SectionHeading>Sign-in methods</SectionHeading>
				<SignInMethods user={user} />
				<SectionHeading>API tokens</SectionHeading>
				<ApiTokens />
			</CardContent>
		</Card>
	);
}

function NameRow({ user }: { user: AuthUser }) {
	const { api } = useApi();
	const { refresh } = useAuth();
	const [name, setName] = useState(user.name ?? "");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const unchanged = name.trim() === (user.name ?? "");

	const save = async (e: FormEvent) => {
		e.preventDefault();
		setBusy(true);
		setError(null);
		try {
			await api.patch("/v1/users/me", { name: name.trim() });
			await refresh();
		} catch (err) {
			setError(authErrorMessage(err));
		} finally {
			setBusy(false);
		}
	};

	return (
		<SettingRow label="Name" description={error ?? undefined}>
			<form onSubmit={save} className="flex gap-2">
				<Input
					aria-label="Name"
					className="h-8 w-48"
					maxLength={100}
					value={name}
					onChange={(e) => setName(e.target.value)}
				/>
				<Button type="submit" size="sm" variant="outline" className="h-8" disabled={busy || unchanged}>
					Save
				</Button>
			</form>
		</SettingRow>
	);
}

function EmailRow({ user }: { user: AuthUser }) {
	const { api } = useApi();
	const { refresh } = useAuth();
	const [stage, setStage] = useState<"idle" | "editing" | "sent">("idle");
	const [newEmail, setNewEmail] = useState("");
	const [code, setCode] = useState("");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const reset = () => {
		setStage("idle");
		setNewEmail("");
		setCode("");
		setError(null);
	};

	const send = async (e: FormEvent) => {
		e.preventDefault();
		setBusy(true);
		setError(null);
		try {
			await api.post("/v1/auth/email/change", { email: newEmail.trim() });
			setStage("sent");
		} catch (err) {
			setError(authErrorMessage(err, NOT_AN_EMAIL));
		} finally {
			setBusy(false);
		}
	};

	const confirm = async (e: FormEvent) => {
		e.preventDefault();
		setBusy(true);
		setError(null);
		try {
			await verifySignIn({ email: newEmail.trim(), code: code.trim() });
			await refresh();
			reset();
		} catch (err) {
			setError(authErrorMessage(err));
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="py-3 border-b border-border last:border-0">
			<div className="flex items-center justify-between gap-4">
				<div className="flex flex-col gap-0.5 min-w-0">
					<span className="text-sm font-medium">Email</span>
					<span className="text-xs text-muted-foreground truncate">{user.email}</span>
				</div>
				{stage === "idle" ? (
					<Button size="sm" variant="outline" className="h-8" onClick={() => setStage("editing")}>
						Change
					</Button>
				) : (
					<Button size="sm" variant="ghost" className="h-8" onClick={reset}>
						Cancel
					</Button>
				)}
			</div>
			{stage === "editing" && (
				<form onSubmit={send} className="mt-3 flex gap-2">
					<Input
						aria-label="New email"
						type="email"
						autoComplete="email"
						placeholder="New email address"
						required
						autoFocus
						className="h-8"
						value={newEmail}
						onChange={(e) => setNewEmail(e.target.value)}
					/>
					<Button type="submit" size="sm" className="h-8 shrink-0" disabled={busy}>
						Send confirmation
					</Button>
				</form>
			)}
			{stage === "sent" && (
				<form onSubmit={confirm} className="mt-3 flex flex-col gap-2">
					<p className="text-xs text-muted-foreground">
						We sent a link and a 6-digit code to <strong>{newEmail.trim()}</strong>. Your email changes once you open
						the link or enter the code.
					</p>
					<div className="flex gap-2">
						<Input
							aria-label="Code"
							inputMode="numeric"
							autoComplete="one-time-code"
							pattern="[0-9]{6}"
							maxLength={6}
							placeholder="Code"
							required
							autoFocus
							className="h-8 w-32"
							value={code}
							onChange={(e) => setCode(e.target.value)}
						/>
						<Button type="submit" size="sm" className="h-8" disabled={busy}>
							Confirm
						</Button>
					</div>
				</form>
			)}
			{error && <p className="mt-2 text-xs text-destructive">{error}</p>}
		</div>
	);
}

function SignInMethods({ user }: { user: AuthUser }) {
	const { api } = useApi();
	const { providers, refresh } = useAuth();
	const [searchParams, setSearchParams] = useSearchParams();
	const [error, setError] = useState<string | null>(null);
	const [busy, setBusy] = useState<OAuthProvider | null>(null);

	// A failed connect comes back here as ?error=<code>
	useEffect(() => {
		const code = searchParams.get("error");
		if (!code) return;
		setError(oauthErrorMessage(code));
		setSearchParams(
			(params) => {
				params.delete("error");
				return params;
			},
			{ replace: true },
		);
	}, [searchParams, setSearchParams]);

	const connected = (provider: OAuthProvider) => user.identities.filter((i) => i.provider === provider);
	// A provider switched off on the server still shows while an identity of it remains, so it can be disconnected
	const shown = (Object.keys(PROVIDER_NAMES) as OAuthProvider[]).filter(
		(p) => providers.includes(p) || connected(p).length > 0,
	);

	const disconnect = async (provider: OAuthProvider) => {
		setBusy(provider);
		setError(null);
		try {
			await api.delete(`/v1/auth/identities/${provider}`);
			await refresh();
		} catch (err) {
			setError(authErrorMessage(err));
		} finally {
			setBusy(null);
		}
	};

	return (
		<div className="flex flex-col">
			<div className="flex items-center justify-between py-3 border-b border-border last:border-0">
				<div className="flex items-center gap-3 min-w-0">
					<Mail className="h-4 w-4 shrink-0 text-muted-foreground" />
					<div className="flex flex-col gap-0.5 min-w-0">
						<span className="text-sm font-medium">Email</span>
						<span className="text-xs text-muted-foreground truncate">A sign-in link to {user.email}</span>
					</div>
				</div>
			</div>
			{shown.map((provider) => {
				const identities = connected(provider);
				return (
					<div key={provider} className="flex items-center justify-between gap-4 py-3 border-b border-border last:border-0">
						<div className="flex items-center gap-3 min-w-0">
							<ProviderIcon provider={provider} className="h-4 w-4 shrink-0" />
							<div className="flex flex-col gap-0.5 min-w-0">
								<span className="text-sm font-medium">{PROVIDER_NAMES[provider]}</span>
								<span className="text-xs text-muted-foreground truncate">
									{identities.length > 0
										? `Connected${identities[0].email ? ` as ${identities.map((i) => i.email).join(", ")}` : ""}`
										: "Not connected"}
								</span>
							</div>
						</div>
						{identities.length > 0 ? (
							<Button
								size="sm"
								variant="outline"
								className="h-8"
								disabled={busy === provider}
								onClick={() => void disconnect(provider)}
							>
								Disconnect
							</Button>
						) : (
							<Button size="sm" variant="outline" className="h-8" asChild>
								<a href={oauthStartUrl(provider, "link", RETURN_TO)}>Connect</a>
							</Button>
						)}
					</div>
				);
			})}
			{error && <p className="mt-2 text-xs text-destructive">{error}</p>}
		</div>
	);
}

interface ApiToken {
	id: string;
	label: string;
	created: string;
	last_used: string;
}

function ApiTokens() {
	const { api } = useApi();
	const [tokens, setTokens] = useState<ApiToken[] | null>(null);
	const [label, setLabel] = useState("");
	const [created, setCreated] = useState<string | null>(null);
	const [copied, setCopied] = useState(false);
	const [confirmingRevoke, setConfirmingRevoke] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		api
			.get<ApiToken[]>("/v1/auth/tokens")
			.then((r) => setTokens(r.data))
			.catch((err) => setError(authErrorMessage(err)));
	}, [api]);

	const create = async (e: FormEvent) => {
		e.preventDefault();
		setError(null);
		try {
			const { data } = await api.post<ApiToken & { token: string }>("/v1/auth/tokens", { label: label.trim() });
			const { token, ...listed } = data;
			setTokens((current) => [...(current ?? []), listed]);
			setCreated(token);
			setCopied(false);
			setLabel("");
		} catch (err) {
			setError(authErrorMessage(err));
		}
	};

	const revoke = async (id: string) => {
		setError(null);
		try {
			await api.delete(`/v1/auth/tokens/${id}`);
			setTokens((current) => (current ?? []).filter((t) => t.id !== id));
		} catch (err) {
			setError(authErrorMessage(err));
		} finally {
			setConfirmingRevoke(null);
		}
	};

	const copy = async () => {
		if (!created) return;
		await navigator.clipboard.writeText(created);
		setCopied(true);
	};

	return (
		<div className="flex flex-col">
			<p className="text-xs text-muted-foreground py-2">
				For the <code className="font-mono">yapit</code> CLI and scripts: set{" "}
				<code className="font-mono">YAPIT_TOKEN</code>, or send it as{" "}
				<code className="font-mono">Authorization: Bearer …</code>. A token works until you revoke it.
			</p>
			{tokens?.map((t) => (
				<div key={t.id} className="flex items-center justify-between gap-4 py-3 border-b border-border">
					<div className="flex items-center gap-3 min-w-0">
						<KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" />
						<div className="flex flex-col gap-0.5 min-w-0">
							<span className="text-sm font-medium truncate">{t.label}</span>
							<span className="text-xs text-muted-foreground">
								Created {formatDate(t.created)} · last used {formatDate(t.last_used)}
							</span>
						</div>
					</div>
					{confirmingRevoke === t.id ? (
						<div className="flex gap-1">
							<Button size="sm" variant="ghost" className="h-8" onClick={() => setConfirmingRevoke(null)}>
								Keep
							</Button>
							<Button size="sm" variant="destructive" className="h-8" onClick={() => void revoke(t.id)}>
								Revoke
							</Button>
						</div>
					) : (
						<Button size="sm" variant="outline" className="h-8" onClick={() => setConfirmingRevoke(t.id)}>
							Revoke
						</Button>
					)}
				</div>
			))}
			{created && (
				<div className="mt-3 rounded-md border border-primary/40 bg-primary/5 p-3 flex flex-col gap-2">
					<span className="text-xs font-medium">Copy your new token now. It won't be shown again.</span>
					<div className="flex gap-2">
						<Input readOnly aria-label="New API token" value={created} className="h-8 font-mono text-xs" onFocus={(e) => e.target.select()} />
						<Button size="sm" variant="outline" className="h-8 shrink-0" onClick={() => void copy()}>
							{copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
							{copied ? "Copied" : "Copy"}
						</Button>
					</div>
				</div>
			)}
			<form onSubmit={create} className="mt-3 flex gap-2">
				<Input
					aria-label="Token name"
					placeholder="Token name, e.g. laptop"
					required
					maxLength={100}
					className="h-8"
					value={label}
					onChange={(e) => setLabel(e.target.value)}
				/>
				<Button type="submit" size="sm" variant="outline" className="h-8 shrink-0" disabled={!label.trim()}>
					Create token
				</Button>
			</form>
			{error && <p className="mt-2 text-xs text-destructive">{error}</p>}
		</div>
	);
}

function formatDate(iso: string): string {
	return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
