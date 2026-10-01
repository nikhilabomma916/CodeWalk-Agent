import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/features/auth/auth-context";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "CodeWalk Agent", template: "%s · CodeWalk Agent" },
  description: "AI-assisted coding environment for writing, understanding, and improving code.",
};

export const viewport: Viewport = {
  themeColor: "#111317",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="h-full overflow-hidden">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
