/**
 * Passwordless email sign-in. `start` emails a 6-digit code; `verify` trades
 * the code for a backend session token (same shape as authService.createSession),
 * which AuthContext.signInWithSession then adopts.
 */
import api from "./api";
import type { SessionResponse } from "./authService";

export async function startEmailAuth(email: string): Promise<void> {
  await api.post("/auth/email/start", { email });
}

export async function verifyEmailCode(
  email: string,
  code: string,
  name?: string,
): Promise<SessionResponse> {
  const { data } = await api.post<SessionResponse>("/auth/email/verify", {
    email,
    code,
    name,
  });
  return data;
}
