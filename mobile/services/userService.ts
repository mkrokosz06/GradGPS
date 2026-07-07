import api from "./api";

export type CreateUserResponse = {
  user_id: string;
  name:    string;
  email:   string;
};

/**
 * Authenticated profile upsert. Identity comes from the Bearer token the
 * api interceptor attaches — the backend derives user_id from the verified
 * token, never from this body.
 */
export async function upsertMe(name?: string, email?: string): Promise<CreateUserResponse> {
  const res = await api.post<CreateUserResponse>("/users/me", { name, email });
  return res.data;
}

/** LEGACY dev-only signup (backend requires AUTH_DEV_BYPASS=1). */
export async function createUser(name: string, email: string): Promise<CreateUserResponse> {
  const res = await api.post<CreateUserResponse>("/users/create", { name, email });
  return res.data;
}
