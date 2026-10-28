import { REGEXP_ONLY_DIGITS } from "input-otp";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";

export const CODE_LENGTH = 6;

/** The emailed 6-digit code: digits only, a pasted code fills every slot, and `onComplete` fires on the last digit. */
export function CodeInput({
	value,
	onChange,
	onComplete,
	disabled,
	className,
}: {
	value: string;
	onChange: (value: string) => void;
	onComplete: (code: string) => void;
	disabled?: boolean;
	className?: string;
}) {
	return (
		<InputOTP
			aria-label="Code"
			maxLength={CODE_LENGTH}
			pattern={REGEXP_ONLY_DIGITS}
			pasteTransformer={(pasted) => pasted.replace(/\D/g, "")}
			autoComplete="one-time-code"
			autoFocus
			disabled={disabled}
			value={value}
			onChange={onChange}
			onComplete={onComplete}
		>
			<InputOTPGroup className={className}>
				{Array.from({ length: CODE_LENGTH }, (_, i) => (
					<InputOTPSlot key={i} index={i} />
				))}
			</InputOTPGroup>
		</InputOTP>
	);
}
