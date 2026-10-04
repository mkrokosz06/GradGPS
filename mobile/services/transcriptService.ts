import api from "./api";
import { invalidateAudit } from "./auditService";
import { invalidateTimeline } from "./timelineService";

/** Every mutation below changes the transcript, and the audit, the timeline and
 *  the Entrance to Major gate are all computed FROM the transcript — so their
 *  caches are stale the instant one of these returns. Dropping them here rather
 *  than at each call site means no screen can render a requirement state we
 *  already know is wrong: the Account checklist was showing a gate course as
 *  still taken after the student swapped it away, because it rendered the
 *  cached timeline on focus before the refetch landed. */
function invalidateDerived(userId: string): void {
  invalidateAudit(userId);
  invalidateTimeline(userId);
}

export type UploadResult = {
  status:          string;
  courses_parsed:  number;
  done:            number;
  in_progress:     number;
  transfer:        number;
  transcript_kind?: string;   // "official" | "unofficial"
  parse_warning?:   string;   // set when an official transcript was parsed best-effort
};

export type TranscriptCourse = {
  course_code:    string;
  grade:          string;
  credits_earned: number;
  status:         string;
  course_title?:  string;
  /** "parsed" | "manual" (student-edited) | "self_reported" (no-transcript mode) */
  source?:        string;
};

export type EditedCourse = {
  course_code:    string;
  grade:          string;
  credits_earned: number;
  status:         string;
  term:           string;
  source:         string;
};

export type TranscriptTerm = {
  term:    string;
  label:   string;
  courses: TranscriptCourse[];
};

export type TranscriptData = {
  has_transcript: boolean;
  /** Every course was entered by the student (no-transcript mode). */
  self_reported?: boolean;
  courses_total:  number;
  terms:          TranscriptTerm[];
};

export async function uploadTranscript(
  userId:   string,
  fileUri:  string,
  fileName: string,
  acknowledgeOfficial = false,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", { uri: fileUri, name: fileName, type: "application/pdf" } as any);
  if (acknowledgeOfficial) form.append("acknowledge_official", "true");
  const res = await api.post<UploadResult>("/transcript/upload", form, {
    headers: { "x-user-id": userId, "Content-Type": "multipart/form-data" },
  });
  invalidateDerived(userId);
  return res.data;
}

/**
 * True when an upload was blocked by the official-transcript consent gate
 * (HTTP 409). The caller should show a confirmation dialog and, if the user
 * agrees, re-call uploadTranscript with acknowledgeOfficial=true.
 */
export function isOfficialAckError(e: any): boolean {
  return e?.response?.status === 409 && e?.response?.data?.detail?.needs_official_ack === true;
}

export async function getTranscript(userId: string): Promise<TranscriptData> {
  const res = await api.get<TranscriptData>("/transcript", {
    headers: { "x-user-id": userId },
  });
  return res.data;
}

export async function deleteTranscript(userId: string): Promise<void> {
  await api.delete("/transcript", {
    headers: { "x-user-id": userId },
  });
  invalidateDerived(userId);
}

/** Add a class the student registered for (stored as an in-progress course). */
export async function addCourse(
  userId:  string,
  courseCode: string,
  term:    string,
  credits: number,
): Promise<EditedCourse> {
  const res = await api.post<{ course: EditedCourse }>(
    "/transcript/course",
    { course_code: courseCode, term, credits_earned: credits },
    { headers: { "x-user-id": userId } },
  );
  invalidateDerived(userId);
  return res.data.course;
}

/** Swap an in-progress class for another (optionally changing credits). */
export async function swapCourse(
  userId:       string,
  originalCode: string,
  newCode:      string,
  credits?:     number,
): Promise<EditedCourse> {
  const res = await api.patch<{ course: EditedCourse }>(
    "/transcript/course",
    { original_code: originalCode, course_code: newCode, credits_earned: credits },
    { headers: { "x-user-id": userId } },
  );
  invalidateDerived(userId);
  return res.data.course;
}

/** Drop an in-progress class from the transcript. */
export async function dropCourse(userId: string, courseCode: string): Promise<void> {
  await api.delete("/transcript/course", {
    params: { course_code: courseCode },
    headers: { "x-user-id": userId },
  });
  invalidateDerived(userId);
}


// ── No-transcript mode ─────────────────────────────────────────────────────────

export type WalkCourse = { code: string; title: string; credits: number };

export type WalkItem =
  | ({ kind: "course" } & WalkCourse)
  | { kind: "choice"; credits: number; options: WalkCourse[] }
  | { kind: "open"; label: string; credits: number; gen_ed?: string | null;
      dept?: string; suggested?: WalkCourse[] };

export type WalkSemester = { year: number; season: "FA" | "SP"; items: WalkItem[] };

export type Walkthrough = {
  major:        string;
  current_term: string;          // e.g. "FA 2026"
  has_plan:     boolean;
  semesters:    WalkSemester[];  // the major's plan, Fall/Spring only
  suggestions:  WalkCourse[];    // quick-add chips for a major with no plan
};

export type SelfReportCourse = {
  course_code: string;
  term:        string;           // "" for transfer / AP credit
  status:      "done" | "in_progress" | "transfer";
  credits?:    number;
  below_c?:    boolean;
};

export async function getWalkthrough(userId: string): Promise<Walkthrough> {
  const res = await api.get<Walkthrough>("/transcript/walkthrough", {
    headers: { "x-user-id": userId },
  });
  return res.data;
}

/** Replace every course with the classes the student entered. */
export async function saveSelfReport(
  userId: string,
  courses: SelfReportCourse[],
): Promise<{ courses_saved: number; done: number; in_progress: number; transfer: number }> {
  const res = await api.post("/transcript/self-report", { courses }, {
    headers: { "x-user-id": userId },
  });
  invalidateDerived(userId);
  return res.data;
}

export type SearchCourse = { course_code: string; course_title: string; credits: number };

/** Search every bulletin course, optionally scoped to a gen-ed domain or subject. */
export async function searchAllCourses(
  q: string,
  opts: { gen_ed?: string | null; dept?: string } = {},
): Promise<SearchCourse[]> {
  const res = await api.get<{ results: SearchCourse[] }>("/courses/search", {
    params: { q, gen_ed: opts.gen_ed || undefined, dept: opts.dept || undefined },
  });
  return res.data.results;
}
