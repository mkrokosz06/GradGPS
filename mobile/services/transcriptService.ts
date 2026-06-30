import api from "./api";

export type UploadResult = {
  status:         string;
  courses_parsed: number;
  done:           number;
  in_progress:    number;
  transfer:       number;
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
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", { uri: fileUri, name: fileName, type: "application/pdf" } as any);
  const res = await api.post<UploadResult>("/transcript/upload", form, {
    headers: { "x-user-id": userId, "Content-Type": "multipart/form-data" },
  });
  return res.data;
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
