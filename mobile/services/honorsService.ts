import api from "./api";
import { invalidateAudit } from "./auditService";
import { invalidateTimeline } from "./timelineService";

/**
 * Schreyer Honors College — the student's own declaration. Honors courses on a
 * transcript already count for everyone; declaring adds what only a Scholar
 * gets, like a major's honors thesis standing in for electives (ME 494H + 493
 * for a technical elective each).
 */

export type SchreyerEntry = "first_year" | "second_year" | "third_year";

export type Honors = { program: "schreyer"; entry: SchreyerEntry };

export const SCHREYER_ENTRIES: { value: SchreyerEntry; label: string }[] = [
  { value: "first_year", label: "Admitted as a first-year" },
  { value: "second_year", label: "Admitted in my second year" },
  { value: "third_year", label: "Admitted in my third year" },
];

/** The student's honors declaration, or null. */
export async function getMyHonors(userId: string): Promise<Honors | null> {
  const res = await api.get<{ honors?: Honors | null }>("/users/me", {
    headers: { "x-user-id": userId },
  });
  return res.data.honors ?? null;
}

/** Declare Schreyer with an admit year, or clear it with null. The plan changes with it. */
export async function setMyHonors(userId: string, entry: SchreyerEntry | null): Promise<Honors | null> {
  const res = await api.put<{ honors: Honors | null }>(
    "/users/me/honors",
    entry ? { program: "schreyer", entry } : { program: null },
    { headers: { "x-user-id": userId } },
  );
  invalidateAudit(userId);
  invalidateTimeline(userId);
  return res.data.honors ?? null;
}
