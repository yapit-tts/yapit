const STORAGE_KEY = "yapit_anonymous_id";

/**
 * Get or create a persistent anonymous user ID.
 * Used for anonymous users to maintain session continuity.
 */
export function getOrCreateAnonymousId(): string {
  let id = localStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}

/**
 * Clear anonymous ID (e.g., when user creates account and claims data)
 */
export function clearAnonymousId(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/**
 * Check if an anonymous ID exists
 */
export function hasAnonymousId(): boolean {
  return localStorage.getItem(STORAGE_KEY) !== null;
}
