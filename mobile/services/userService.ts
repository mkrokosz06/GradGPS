import api from "./api";

export type CreateUserResponse = {
  user_id: string;
  name:    string;
  email:   string;
};

export async function createUser(name: string, email: string): Promise<CreateUserResponse> {
  const res = await api.post<CreateUserResponse>("/users/create", { name, email });
  return res.data;
}
