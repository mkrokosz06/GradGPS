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
};

export type Semester = {
  term:    string;
  label:   string;
  status:  "completed" | "current" | "upcoming";
  credits: number;
  courses: TimelineCourse[];
};

export type TimelineData = {
  major:              string;
  subplan:            string | null;
  transcript_credits: number;
  semesters:          Semester[];
};

export async function getTimeline(userId: string): Promise<TimelineData> {
  const res = await api.get<TimelineData>("/timeline", { headers: { "x-user-id": userId } });
  return res.data;
}
