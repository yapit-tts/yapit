import * as Sentry from "@sentry/react";

const dsn = import.meta.env.VITE_SENTRY_DSN;

if (dsn) {
	Sentry.init({
		dsn,
		environment: import.meta.env.MODE,
		integrations: [Sentry.httpClientIntegration()],
	});
}
