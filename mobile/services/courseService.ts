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
