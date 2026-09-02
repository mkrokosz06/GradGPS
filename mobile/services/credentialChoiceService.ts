import api from "./api";

/**
 * Student-confirmed credential requirements.
 *
 * Some PSU minors state a requirement the bulletin never resolves into a course
 * list — "Select 6 credits from an approved list in consultation with the minor
 * adviser". There is nothing for the audit to check, so the student names the
 * courses they used and those count.
 *
 * Same trust model as substitutions: the student's own claim, capped, and limited
 * to courses actually on their transcript so the credit total stays real.
 */

/** Attested courses keyed by `"<program>|<requirement group>"`. */
export type CredentialChoiceMap = Record<string, string[]>;

/** How the backend addresses one requirement (credential_choices.group_key). */
export function requirementKey(program: string, requirementGroup: string): string {
  return `${program}|${requirementGroup}`;
}

export async function getCredentialChoices(userId: string): Promise<CredentialChoiceMap> {
  const res = await api.get<{ choices: CredentialChoiceMap }>("/credential-choices", {
    headers: { "x-user-id": userId },
  });
  return res.data.choices ?? {};
}

export async function addCredentialChoice(
  userId: string,
  program: string,
  requirementGroup: string,
  courseCode: string,
): Promise<CredentialChoiceMap> {
  const res = await api.put<{ choices: CredentialChoiceMap }>(
    "/credential-choices",
    { program, requirement_group: requirementGroup, course_code: courseCode },
    { headers: { "x-user-id": userId } },
  );
  return res.data.choices ?? {};
}

export async function removeCredentialChoice(
  userId: string,
  program: string,
  requirementGroup: string,
  courseCode: string,
): Promise<CredentialChoiceMap> {
  const res = await api.delete<{ choices: CredentialChoiceMap }>("/credential-choices", {
    params: { program, requirement_group: requirementGroup, course_code: courseCode },
    headers: { "x-user-id": userId },
  });
  return res.data.choices ?? {};
}

/** The backend's plain-English reason ("not on your transcript yet", the cap, …). */
export function credentialChoiceError(e: any): string {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string"
    ? detail
    : "Could not save that. Please check your connection and try again.";
}
