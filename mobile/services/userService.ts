import api from "./api";

export type CreateUserResponse = {
  user_id: string;
  name:    string;
  email:   string;
};

export type MeResponse = {
  user_id: string;
  name:    string;
  email:   string;
  major:   string | null;
  subplan: string | null;
};

/**
 * Fetch the caller's stored profile. Identity comes from the Bearer token the
 * api interceptor attaches. Throws (404) when no profile record exists yet.
 */
export async function getMe(): Promise<MeResponse> {
  const res = await api.get<MeResponse>("/users/me");
  return res.data;
}

/**
 * Authenticated profile upsert. Identity comes from the Bearer token the
 * api interceptor attaches — the backend derives user_id from the verified
 * token, never from this body.
 */
export async function upsertMe(name?: string, email?: string): Promise<CreateUserResponse> {
  const res = await api.post<CreateUserResponse>("/users/me", { name, email });
  return res.data;
}

/**
 * Permanently delete the caller's account — stored transcript PDF, parsed
 * courses, profile, and all server sessions. Irreversible.
 */
export async function deleteAccount(): Promise<void> {
  await api.delete("/users/me");
}

/** LEGACY dev-only signup (backend requires AUTH_DEV_BYPASS=1). */
export async function createUser(name: string, email: string): Promise<CreateUserResponse> {
  const res = await api.post<CreateUserResponse>("/users/create", { name, email });
  return res.data;
}
