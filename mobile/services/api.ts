import axios from "axios";
import { API_BASE } from "../constants/api";

const api = axios.create({
  baseURL: API_BASE,
  timeout: 15_000,
  headers: { "Content-Type": "application/json" },
});

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
  return config;
});

export default api;
