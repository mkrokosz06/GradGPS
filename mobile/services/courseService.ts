import axios from "axios";
import { API_BASE } from "../constants/api";
import api from "./api";

// Longer timeout for course endpoints — /courses/{code} chains a live PSU bulletin scrape
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

export type GenEdDomain = {
  code:  string;
  label: string;
  // Credit accounting for the domain (absent on older backends).
  required?:  number;   // credits the domain needs
  completed?: number;   // credits already done on the transcript
  selected?:  number;   // credits planned (picked in the timeline) but not yet taken
  remaining?: number;   // required − completed − selected
};

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

/** The gen-ed domains the student still needs — the picker's domain chips. Pass
 *  `excludeSlot` (the slot being edited) so its own pick doesn't hide its domain. */
export async function getGenEdDomains(
  userId: string,
  excludeSlot?: string,
): Promise<GenEdDomain[]> {
  const res = await api.get<{ domains: GenEdDomain[] }>(
    "/courses/gen-ed-domains",
    {
      params: { exclude_slot: excludeSlot || undefined },
      headers: { "x-user-id": userId },
    },
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

export async function getCourseDetail(code: string): Promise<CourseDetail> {
  const res = await courseApi.get<CourseDetail>(`/courses/${encodeURIComponent(code)}`);
  return res.data;
}
