import api from "./api";

export type PoolCourse = {
  course_code:  string;
  course_title: string;
  credits:      number;
};

export type SlotOption = {
  course_code:  string;
  course_title: string;
  credits:      number;
};

export type SlotKind = "course" | "choose_one" | "pool" | "gen_ed" | "elective";

export type TimelineCourse = {
  course_code:          string;
  course_title?:        string;
  grade:                string;
  credits_earned:       number;
  status:               "done" | "in_progress" | "missing";
  is_pool?:             boolean;
  gen_ed_categories?:   string[];
  pool_courses?:        PoolCourse[];
  pool_needed_credits?: number;
  pool_needed_courses?: number;
  pool_ref?:            string;
  // Class selector (present on actionable future slots).
  slot_key?:            string | null;
  slot_kind?:           SlotKind | null;
  options?:             SlotOption[] | null;
  chosen_code?:         string | null;
  pinned?:              boolean;
  pin_moved?:           boolean;
  searchable?:          boolean;
  // Set when the slot comes from a declared minor / certificate rather than the
  // major, so the card can say which one put it in the plan.
  credential?:          string | null;
  credential_short?:    string | null;
  // An adviser-defined credential requirement: shown in the bulletin's own words
  // and never auto-satisfied, so there is no course picker to offer.
  needs_confirmation?:  boolean;
  /** The requirement's full size, so a partly-confirmed one can show "6 of 9". */
  requirement_credits?: number | null;
};

export type Semester = {
  term:    string;
  label:   string;
  status:  "completed" | "current" | "upcoming";
  credits: number;
  courses: TimelineCourse[];
};

/** One requirement of the Entrance to Major gate: take any ONE branch in full.
 *  A branch is normally a single course, but PSU writes compound ones
 *  ("ACCTG 211 or (ACCTG 201 and ACCTG 202)") where every code is required. */
export type EntranceBranch = {
  codes:  string[];
  status: "done" | "in_progress" | "below_grade" | "partial" | "missing";
};

export type EntranceGroup = {
  branches: EntranceBranch[];
  status:   EntranceBranch["status"];
  /** Every code the gate lists for this group. */
  options:  string[];
  /** The timeline slot this group maps to. Absent once the group is satisfied —
   *  there is nothing left to schedule, so nothing to write against. */
  slot_key?:  string;
  slot_kind?: SlotKind;
  /** The subset of `options` this slot actually offers. Empty for a named
   *  single-course slot, which is still pinnable to a semester. */
  choosable?: string[];
};

export type EntranceToMajor = {
  /** `courses_met` means the COURSES are done — never that the student is in.
   *  `needs_confirmation` means PSU states something GradGPS cannot check. */
  status:             "courses_met" | "in_progress" | "not_started"
                      | "needs_confirmation" | "no_course_requirements";
  groups:             EntranceGroup[];
  groups_done:        number;
  groups_total:       number;
  remaining_courses:  string[];
  gpa_min:            number | null;
  gpa_candidates:     number[];
  min_grade:          string | null;
  semester_standing:  number | null;
  needs_confirmation: boolean;
  /** PSU's own wording for anything we could not check. Render verbatim. */
  notes:              string[];
  source_url:         string | null;
};

export type TimelineData = {
  major:              string;
  subplan:            string | null;
  transcript_credits: number;
  semesters:          Semester[];
  /** `null` for the majors that publish no gate, and absent on older backends. */
  entrance_to_major?: EntranceToMajor | null;
};

// Last successful timeline per user, so the Account checklist can render from
// cache on focus instead of blocking on a fetch it shares with Home/Timeline.
const timelineCache = new Map<string, TimelineData>();

export function getCachedTimeline(userId: string): TimelineData | null {
  return timelineCache.get(userId) ?? null;
}

export async function getTimeline(userId: string): Promise<TimelineData> {
  const res = await api.get<TimelineData>("/timeline", { headers: { "x-user-id": userId } });
  timelineCache.set(userId, res.data);
  return res.data;
}
