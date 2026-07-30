import axios, {
  AxiosError,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";
import type { ApiError, TokenPair } from "./types";
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "./tokenStore";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export const api = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// Attach the current access token to every request.
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ---------------------------------------------------------------------------
// Transparent refresh-on-401
//
// A 401 usually means the short-lived access token expired. We refresh once,
// using the rotating refresh token, and replay the original request. Refreshes
// are single-flighted: a burst of parallel requests that all 401 shares one
// refresh call rather than spending (and invalidating) the refresh token N
// times. If the refresh itself fails, the session is over — tokens are cleared
// and the tokenStore listeners send the user to login.
// ---------------------------------------------------------------------------
let refreshing: Promise<string> | null = null;

// A separate axios instance so the refresh call does not recurse through this
// interceptor.
const refreshClient = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
});

async function refreshAccessToken(): Promise<string> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) throw new Error("no refresh token");
  const { data } = await refreshClient.post<TokenPair>("/auth/refresh", {
    refresh_token: refreshToken,
  });
  setTokens({ accessToken: data.access_token, refreshToken: data.refresh_token });
  return data.access_token;
}

interface RetriableConfig extends AxiosRequestConfig {
  _retried?: boolean;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<{ error?: ApiError }>) => {
    const original = error.config as (RetriableConfig & InternalAxiosRequestConfig) | undefined;
    const status = error.response?.status;

    const isRefreshCall = original?.url?.includes("/auth/refresh");
    if (status === 401 && original && !original._retried && !isRefreshCall && getRefreshToken()) {
      original._retried = true;
      try {
        refreshing = refreshing ?? refreshAccessToken().finally(() => (refreshing = null));
        const token = await refreshing;
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      } catch {
        clearTokens();
      }
    }
    return Promise.reject(error);
  },
);

/** Pull the server's structured error out of an Axios failure. */
export function toApiError(error: unknown): ApiError {
  if (axios.isAxiosError(error)) {
    const payload = error.response?.data as { error?: ApiError } | undefined;
    if (payload?.error) return payload.error;
    if (error.response) {
      return {
        code: `http_${error.response.status}`,
        message: error.response.statusText || "Request failed",
      };
    }
    return { code: "network_error", message: "Cannot reach the server." };
  }
  return { code: "unknown", message: "An unexpected error occurred." };
}

/** Human-friendly message for a caught error, ready to show in the UI. */
export function errorMessage(error: unknown): string {
  return toApiError(error).message;
}
