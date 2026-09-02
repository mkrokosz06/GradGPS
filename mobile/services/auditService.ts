import api from "./api";
import type { CredentialAudit } from "./credentialService";

export type AuditSummary = {
  major:              string;
  subplan:            string | null;
  transcript_credits: number;
  total:              number;
  done:               number;
  in_progress:        number;
  missing:            number;
  /** Declared minors / certificates, each with its own audit. Absent on older
   *  backends, so every consumer must tolerate undefined. */
  credentials?:       CredentialAudit[];
};

// Last successful audit per user, so screens can render instantly on focus
// while a fresh fetch runs in the background.
const auditCache = new Map<string, AuditSummary>();

export function getCachedAudit(userId: string): AuditSummary | null {
  return auditCache.get(userId) ?? null;
}

export async function getAudit(userId: string): Promise<AuditSummary> {
  const res = await api.get<AuditSummary>("/audit", { headers: { "x-user-id": userId } });
  auditCache.set(userId, res.data);
  return res.data;
}
