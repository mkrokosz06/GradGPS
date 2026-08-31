import axios from "axios";
import * as Application from "expo-application";
import { API_BASE } from "../constants/api";

const api = axios.create({
  baseURL: API_BASE,
  timeout: 15_000,
  headers: { "Content-Type": "application/json" },
});

// Native marketing version of the running build (CFBundleShortVersionString on
// iOS). Null on Expo web / dev — we just omit the header there. Sent on every
// request so the backend can record which build each user is on (admin dash).
const APP_VERSION = Application.nativeApplicationVersion ?? "";

// ── Auth header injection ────────────────────────────────────────────────────
// Set by AuthContext. When a real ID token exists it is sent as
// Authorization: Bearer and the backend ignores any x-user-id header.
// The x-user-id headers still set by individual services only work against
// a backend running with AUTH_DEV_BYPASS=1 (local dev).
let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

api.interceptors.request.use((config) => {
  if (authToken) {
    config.headers.Authorization = `Bearer ${authToken}`;
  }
  if (APP_VERSION) {
    config.headers["X-App-Version"] = APP_VERSION;
  }
  return config;
});

// ── Session expiry handling ──────────────────────────────────────────────────
// AuthContext registers a callback that clears local auth state, sending the
// user back through sign-in. Only fires when a real token was attached (a 401
// in the dev x-user-id flow means something else) and never for the session
// exchange itself (a bad Google token there is handled by the sign-in screen).
let onUnauthorized: (() => void) | null = null;

export function setOnUnauthorized(cb: (() => void) | null) {
  onUnauthorized = cb;
}

api.interceptors.response.use(undefined, (error) => {
  const isSessionExchange = error?.config?.url?.includes("/auth/session");
  if (error?.response?.status === 401 && authToken && !isSessionExchange) {
    onUnauthorized?.();
  }
  return Promise.reject(error);
});

export default api;
