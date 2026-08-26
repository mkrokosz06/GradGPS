import axios from "axios";
import { API_BASE } from "../constants/api";
import api from "./api";

// Longer timeout for course endpoints — they chain PSU scrape + professor rating calls
const courseApi = axios.create({
  baseURL: API_BASE,
  timeout: 35_000,
  headers: { "Content-Type": "application/json" },
});

export type CourseDetail = {
  course_code:  string;
  course_title: string;
  credits:      number;
  description:  string | null;
};

export type SlotCourse = {
  course_code:    string;
  course_title:   string;
  credits:        number;
  multi_category: boolean;
};

export type GenEdDomain = { code: string; label: string };

/** Search the courses that can validly fill a class-selector slot (gen-ed slots
 *  and world-language pools). `q` filters server-side; `category` overrides the
 *  gen-ed domain to search; `needs_query` is true when the universe is too large
 *  to return without a query. */
export async function searchSlotCourses(
  userId: string,
  slotKey: string,
  q: string,
  category?: string,
): Promise<{ results: SlotCourse[]; needs_query: boolean }> {
  const res = await api.get<{ results: SlotCourse[]; needs_query: boolean }>(
    "/courses/for-slot",
    {
      params: { slot_key: slotKey, q: q || undefined, category: category || undefined },
      headers: { "x-user-id": userId },
    },
  );
  return res.data;
}

/** The gen-ed domains the student still needs — the picker's domain chips. */
export async function getGenEdDomains(userId: string): Promise<GenEdDomain[]> {
  const res = await api.get<{ domains: GenEdDomain[] }>(
    "/courses/gen-ed-domains",
    { headers: { "x-user-id": userId } },
  );
  return res.data.domains;
}

export type BreadthArea = { area: string; structure?: string | null; courses: SlotCourse[] };

/** Business Breadth areas the student can pick from (own major area excluded),
 *  each a two-piece sequence, plus a coverage disclaimer — the picker's chips. */
export async function getBreadthAreas(
  userId: string,
): Promise<{ areas: BreadthArea[]; disclaimer: string }> {
  const res = await api.get<{ areas: BreadthArea[]; disclaimer: string }>(
    "/courses/breadth-areas",
    { headers: { "x-user-id": userId } },
  );
  return res.data;
}

export type ProfessorRating = {
  id:                      string;
  name:                    string;
  department:              string | null;
  // Course-specific aggregates
  course_avg_rating:       number | null;
  course_avg_difficulty:   number | null;
  course_would_take_again: number | null;  // percentage 0-100
  course_num_ratings:      number;
  // Overall aggregates (for context when course count is low)
  overall_avg_rating:      number | null;
  overall_avg_difficulty:  number | null;
  overall_would_take_again: number | null;
  overall_num_ratings:     number | null;
};

export async function getCourseDetail(code: string): Promise<CourseDetail> {
  const res = await courseApi.get<CourseDetail>(`/courses/${encodeURIComponent(code)}`);
  return res.data;
}

/** Auto-detect instructors from PSU schedule and return their course-specific ratings. */
export async function getProfessors(
  code: string,
): Promise<{ professors: ProfessorRating[]; schedule_found: boolean }> {
  const res = await courseApi.get<{ professors: ProfessorRating[]; schedule_found: boolean }>(
    `/courses/${encodeURIComponent(code)}/professors`,
  );
  return res.data;
}

/** Manual fallback: search by professor name. */
export async function getProfessorByName(
  code: string,
  professorName: string,
): Promise<ProfessorRating[]> {
  const res = await courseApi.get<{ professors: ProfessorRating[] }>(
    `/courses/${encodeURIComponent(code)}/professor`,
    { params: { name: professorName } },
  );
  return res.data.professors;
}
