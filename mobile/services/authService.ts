/**
 * Session exchange: after Google/Apple sign-in, trade the short-lived (~1 h)
 * ID token for a long-lived backend session token (30-day sliding expiry).
 * The session token is what gets stored and sent as Bearer thereafter.
 */
import api from "./api";

export type SessionResponse = {
  session_token: string;
  expires_at: number;
  user_id: string;
  name: string | null;
  email: string | null;
};

export async function createSession(idToken: string): Promise<SessionResponse> {
  const { data } = await api.post<SessionResponse>("/auth/session", {
    id_token: idToken,
  });
  return data;
}

/** Best-effort revoke of the current session (sign-out). Never throws. */
export async function revokeSession(): Promise<void> {
  try {
    await api.delete("/auth/session");
  } catch {
    // Offline or already expired — local sign-out proceeds regardless.
  }
}
