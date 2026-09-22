import api from "./api";
import type { CredentialAudit } from "./credentialService";
import type { EntranceToMajor } from "./timelineService";

export type {
  EntranceToMajor, EntranceGroup, EntranceBranch,
} from "./timelineService";

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
  /** Entrance-to-Major gate — status only. The interactive checklist needs each
   *  group's timeline slot, which only GET /timeline knows, so the type lives
   *  in timelineService and is re-exported here rather than declared twice.
   *  `null` for the majors that publish no gate; absent on older backends. */
  entrance_to_major?: EntranceToMajor | null;
};

// Last successful audit per user, so screens can render instantly on focus
// while a fresh fetch runs in the background.
const auditCache = new Map<string, AuditSummary>();

export function getCachedAudit(userId: string): AuditSummary | null {
  return auditCache.get(userId) ?? null;
}

/** Drop the cached audit so no screen renders a requirement state we already
 *  know is out of date. Called by every transcript mutation — the audit is
 *  computed from the transcript, so an edit invalidates it by definition. */
export function invalidateAudit(userId?: string): void {
  if (userId) auditCache.delete(userId);
  else auditCache.clear();
}

export async function getAudit(userId: string): Promise<AuditSummary> {
  const res = await api.get<AuditSummary>("/audit", { headers: { "x-user-id": userId } });
  auditCache.set(userId, res.data);
  return res.data;
}
