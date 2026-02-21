import axios from "axios";

const STORAGE_KEY = "yapit_anonymous_id";
const TOKEN_STORAGE_KEY = "yapit_anonymous_token";

const baseURL = import.meta.env.VITE_API_BASE_URL;

async function fetchAnonymousSession(): Promise<{ id: string; token: string }> {
  const { data } = await axios.post(`${baseURL}/v1/users/anonymous-session`);
  return data;
}

export async function getOrCreateAnonymousId(): Promise<string> {
  let id = localStorage.getItem(STORAGE_KEY);
  if (id && localStorage.getItem(TOKEN_STORAGE_KEY)) {
    return id;
  }

  const session = await fetchAnonymousSession();
  localStorage.setItem(STORAGE_KEY, session.id);
  localStorage.setItem(TOKEN_STORAGE_KEY, session.token);
  return session.id;
}

export function getAnonymousToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function clearAnonymousId(): void {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function hasAnonymousId(): boolean {
  return localStorage.getItem(STORAGE_KEY) !== null;
}
