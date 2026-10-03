import { redirect } from "next/navigation";

import { DEFAULT_APP_PATH } from "@/features/auth/redirects";

export default function AppIndexPage() {
  redirect(DEFAULT_APP_PATH);
}
