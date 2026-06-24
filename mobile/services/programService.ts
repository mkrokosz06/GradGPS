import api from "./api";

export async function getAllPrograms(): Promise<string[]> {
  const res = await api.get<{ results: string[] }>("/programs/all");
  return res.data.results;
}

export async function getSubplans(major: string): Promise<string[]> {
  const res = await api.get<{ subplans: string[] }>("/audit/subplans", { params: { major } });
  return res.data.subplans ?? [];
}

export async function selectMajor(
  userId: string,
  major: string,
  subplan: string | null,
): Promise<void> {
  await api.post(
    "/programs/select",
    { major, subplan },
    { headers: { "x-user-id": userId } },
  );
}
