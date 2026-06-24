import api from "./api";

export type UploadResult = {
  status:         string;
  courses_parsed: number;
  done:           number;
  in_progress:    number;
  transfer:       number;
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
