import api from "./api";

/** A course from the student's own transcript, offered as a stand-in for a
 *  requirement. `already_used` means the audit already credits it somewhere —
 *  still selectable (advisers do approve double-counts), just flagged. */
export type SubstitutionCandidate = {
  course_code:  string;
  course_title: string;
  credits:      number;
  grade:        string;
  term:         string;
  status:       "done" | "in_progress" | "transfer";
  already_used: boolean;
  selected:     boolean;
};

export type CandidatesResponse = {
  requirement_code: string;
  /** The course currently declared for this requirement, if any. */
  current:    string | null;
  candidates: SubstitutionCandidate[];
};

export type Substitution = {
  requirement_code:  string;
  substitute_course: string;
  created_at:        string;
};

export async function getCandidates(
  userId: string,
  requirementCode: string,
): Promise<CandidatesResponse> {
  const { data } = await api.get("/substitutions/candidates", {
    params:  { requirement_code: requirementCode },
    headers: { "x-user-id": userId },
  });
  return data;
}

export async function listSubstitutions(userId: string): Promise<Substitution[]> {
  const { data } = await api.get("/substitutions", { headers: { "x-user-id": userId } });
  return data.substitutions ?? [];
}

/** Declare "this course I took counts for that requirement". */
export async function putSubstitution(
  userId: string,
  requirementCode: string,
  substituteCourse: string,
): Promise<void> {
  await api.put(
    "/substitutions",
    { requirement_code: requirementCode, substitute_course: substituteCourse },
    { headers: { "x-user-id": userId } },
  );
}

export async function deleteSubstitution(
  userId: string,
  requirementCode: string,
): Promise<void> {
  await api.delete("/substitutions", {
    params:  { requirement_code: requirementCode },
    headers: { "x-user-id": userId },
  });
}

/** Server-side rejections carry a human-readable `detail`; surface it verbatim
 *  (it explains *why*, e.g. "ESC 120 is already counting for ENGR 100"). */
export function substitutionErrorMessage(e: any): string {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string"
    ? detail
    : "Couldn't save that right now — please try again.";
}
