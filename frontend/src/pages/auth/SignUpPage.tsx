import { SignUp } from "@stackframe/react";
import AuthPageLayout from "./AuthPageLayout";

export default function SignUpPage() {
	return (
		<AuthPageLayout>
			<SignUp fullPage={false} automaticRedirect />
		</AuthPageLayout>
	);
}
