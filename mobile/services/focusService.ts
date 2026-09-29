import api from "./api";
import { invalidateAudit } from "./auditService";
import { invalidateTimeline } from "./timelineService";

/**
 * Application Focus — a block of credits a major requires from ONE area the
 * student chooses (ETI: 12 credits, e.g. Business Competency; Data Sciences,
 * HCDD, Cybersecurity, IT Ethics). Until a focus is picked the audit accepts any
 * mix of every area's courses; once picked, only that area counts, including
 * rules like ETI Business Competency's "no double-counting with the major".
 */

export type FocusArea = {
  name: string;
  /** Credits the area requires (15 for ETI Business Competency: 12 + the major's 3). */
  credits: number;
  courses: string[];
};

/** The focus areas the student's major offers — empty when it has none. */
export async function getFocusAreas(userId: string, major: string): Promise<FocusArea[]> {
  const res = await api.get<{ areas: FocusArea[] }>("/programs/focus-areas", {
    params: { major },
    headers: { "x-user-id": userId },
  });
  return res.data.areas ?? [];
}

/** The student's chosen focus, or null. */
export async function getMyFocus(userId: string): Promise<string | null> {
  const res = await api.get<{ focus?: string | null }>("/users/me", {
    headers: { "x-user-id": userId },
  });
  return res.data.focus ?? null;
}

/** Choose (or clear with null) the focus. The audit and plan change with it. */
export async function setMyFocus(userId: string, focus: string | null): Promise<string | null> {
  const res = await api.put<{ focus: string | null }>(
    "/users/me/focus",
    { focus },
    { headers: { "x-user-id": userId } },
  );
  invalidateAudit(userId);
  invalidateTimeline(userId);
  return res.data.focus ?? null;
}
