import api from "./api";

export type TimelineCourse = {
  course_code:    string;
  course_title?:  string;
  grade:          string;
  credits_earned: number;
  status:         "done" | "in_progress" | "missing";
  is_pool?:       boolean;
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
