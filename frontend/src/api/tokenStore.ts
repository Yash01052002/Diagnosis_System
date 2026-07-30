// A tiny module holding the auth tokens. Kept out of React state so the Axios
// interceptors can read and rotate them without a component in scope. Tokens
// live in localStorage so a page reload keeps the session; the access token is
// short-lived and the refresh token is single-use and rotated on every use.

const ACCESS_KEY = "blackbox.accessToken";
const REFRESH_KEY = "blackbox.refreshToken";

export interface Tokens {
  accessToken: string;
  refreshToken: string;
}

let access: string | null = localStorage.getItem(ACCESS_KEY);
let refresh: string | null = localStorage.getItem(REFRESH_KEY);

type Listener = () => void;
const listeners = new Set<Listener>();

/** Subscribe to token clears (e.g. to redirect to login on session end). */
export function onTokensCleared(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAccessToken(): string | null {
  return access;
}

export function getRefreshToken(): string | null {
  return refresh;
}

export function setTokens(tokens: Tokens): void {
  access = tokens.accessToken;
  refresh = tokens.refreshToken;
  localStorage.setItem(ACCESS_KEY, tokens.accessToken);
  localStorage.setItem(REFRESH_KEY, tokens.refreshToken);
}

export function clearTokens(): void {
  access = null;
  refresh = null;
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  listeners.forEach((fn) => fn());
}

export function hasTokens(): boolean {
  return Boolean(access && refresh);
}
