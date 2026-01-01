import { SignIn } from "@stackframe/react";
import AuthPageLayout from "./AuthPageLayout";

export default function SignInPage() {
	return (
		<AuthPageLayout>
			<SignIn fullPage={false} automaticRedirect />
		</AuthPageLayout>
	);
}
