import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router";
import NotFoundPage from "./NotFoundPage";

/**
 * Extracts a URL from a catch-all route path.
 * Handles: /example.com/path, /https://example.com/path, /https:/example.com/path (collapsed)
 * Returns null for non-URL paths (no dot in first segment, no protocol prefix).
 */
function extractUrl(pathname: string, searchAndHash: string): string | null {
	const raw = pathname.slice(1);
	if (!raw) return null;

	// Protocol prefix — handles both :// and :/ (browser may collapse double slash)
	const protocolMatch = raw.match(/^(https?):\/?\/?(.+)/);
	if (protocolMatch) {
		const [, protocol, rest] = protocolMatch;
		return `${protocol}://${rest}${searchAndHash}`;
	}

	// Bare domain — first path segment contains a dot (TLD heuristic)
	const firstSegment = raw.split("/")[0];
	if (firstSegment.includes(".")) {
		return `https://${raw}${searchAndHash}`;
	}

	return null;
}

export default function UrlCatchAllPage() {
	const location = useLocation();
	const navigate = useNavigate();

	const url = extractUrl(location.pathname, location.search + location.hash);

	useEffect(() => {
		if (url) {
			navigate("/", { state: { prefillUrl: url }, replace: true });
		}
	}, [url, navigate]);

	if (!url) return <NotFoundPage />;

	return null;
}
