import api from "./api";

/**
 * Minors & certificates — coursework a student declares *in addition* to their
 * major. Declared from the Account screen, never during onboarding: signup stays
 * "one major, one transcript, done".
 *
 * The backend serves these from a bundled, verified catalog (backend/credential_catalog.py)
 * rather than the requirements table — see docs/minors-certificates.md.
 */

export type CredentialSummary = {
  program_name: string;
  kind: "minor" | "certificate";
  college: string;
  credits: { min: number; max: number };
  /** Credits the bulletin defers to an adviser, so the UI can say so up front. */
  manual_credits: number;
};

/** One declared credential, as stored on the user record. */
export type DeclaredCredential = {
  program: string;
  kind: "minor" | "certificate";
};

/** A credential's audit, as returned inside GET /audit. */
export type CredentialAudit = {
  program: string;
  kind: "minor" | "certificate";
  done: number;
  in_progress: number;
  missing: number;
  total: number;
  credits_earned: number;
  catalog_credits: { min: number; max: number };
  manual_credits: number;
  url: string;
  groups: any[];
};

/**
 * Search the declarable minors/certificates. Omit `q` for the full list.
 *
 * `userId` rides along as `x-user-id`, the header the AUTH_DEV_BYPASS backend uses
 * in local dev / Expo Go — every other service does the same (see services/api.ts).
 * A real build sends a Bearer token and the backend ignores this header.
 */
export async function searchCredentials(userId: string, q?: string): Promise<CredentialSummary[]> {
  const res = await api.get<{ results: CredentialSummary[] }>("/programs/credentials", {
    params: q ? { q } : undefined,
    headers: { "x-user-id": userId },
  });
  return res.data.results ?? [];
}

/**
 * Replace the caller's declared credentials. The whole list is sent every time —
 * idempotent, and there's no add/remove race for the client to lose.
 */
export async function setCredentials(
  userId: string,
  programs: string[],
): Promise<DeclaredCredential[]> {
  const res = await api.put<{ credentials: DeclaredCredential[] }>(
    "/users/me/credentials",
    { programs },
    { headers: { "x-user-id": userId } },
  );
  return res.data.credentials ?? [];
}

/** Human-readable message from a failed declaration (cap, unknown program, …). */
export function credentialErrorMessage(e: any): string {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string"
    ? detail
    : "Could not save. Please check your connection and try again.";
}

/** "Minor" / "Certificate" for a chip. */
export function kindLabel(kind: string): string {
  return kind === "certificate" ? "CERTIFICATE" : "MINOR";
}

/** "18 cr" or "18-21 cr" — credentials often state a range. */
export function creditLabel(credits?: { min: number; max: number }): string {
  if (!credits) return "";
  const { min, max } = credits;
  return max && max !== min ? `${min}-${max} cr` : `${min} cr`;
}
