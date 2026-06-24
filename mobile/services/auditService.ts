import api from "./api";

export type AuditSummary = {
  major:              string;
  subplan:            string | null;
  transcript_credits: number;
  total:              number;
  done:               number;
  in_progress:        number;
  missing:            number;
};

export async function getAudit(userId: string): Promise<AuditSummary> {
  const res = await api.get<AuditSummary>("/audit", { headers: { "x-user-id": userId } });
  return res.data;
}
