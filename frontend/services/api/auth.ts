import { z } from "zod";

import { apiClient, type ApiClient } from "./client";
import { isApiError } from "./errors";

/** Mirrors backend `app.schemas.auth.UserResponse` (never contains credentials). */
const userSchema = z.object({
  id: z.string(),
  name: z.string(),
  email: z.string(),
  created_at: z.string(),
  last_login_at: z.string().nullable(),
});

export type User = z.infer<typeof userSchema>;

const noContent = z.undefined();

export async function register(
  input: { name: string; email: string; password: string },
  client: ApiClient = apiClient,
): Promise<User> {
  const { data } = await client.request("/auth/register", {
    method: "POST",
    body: input,
    schema: userSchema,
  });
  return data;
}

export async function login(
  input: { email: string; password: string },
  client: ApiClient = apiClient,
): Promise<User> {
  const { data } = await client.request("/auth/login", {
    method: "POST",
    body: input,
    schema: userSchema,
  });
  return data;
}

export async function logout(client: ApiClient = apiClient): Promise<void> {
  await client.request("/auth/logout", { method: "POST", schema: noContent });
}

/** The signed-in user, or null when there is no valid session. Other failures throw. */
export async function currentUser(client: ApiClient = apiClient): Promise<User | null> {
  try {
    return (await client.request("/auth/me", { schema: userSchema })).data;
  } catch (error) {
    if (isApiError(error) && error.status === 401) return null;
    throw error;
  }
}
