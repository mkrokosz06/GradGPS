import api from "./api";

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
};

export type TranscriptTerm = {
  term:    string;
  label:   string;
  courses: TranscriptCourse[];
};

export type TranscriptData = {
  has_transcript: boolean;
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
}
