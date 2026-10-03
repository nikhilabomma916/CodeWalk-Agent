import type { Metadata } from "next";

import { LoginForm } from "@/features/auth/auth-forms";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return <LoginForm />;
}
