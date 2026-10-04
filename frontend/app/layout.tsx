import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { connection } from "next/server";
import type { ReactNode } from "react";

import { AuthProvider } from "@/features/auth/auth-context";
import { ThemeProvider } from "@/features/theme/theme-context";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "CodeWalk Agent", template: "%s · CodeWalk Agent" },
  description: "AI-assisted coding environment for writing, understanding, and improving code.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafaf8" },
    { media: "(prefers-color-scheme: dark)", color: "#131b36" },
  ],
  colorScheme: "dark light",
};

export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  // Render per request: the nonce-based Content-Security-Policy (proxy.ts) needs a fresh nonce
  // in every page, which statically prerendered HTML cannot carry.
  await connection();
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    // data-theme is set only by the head script (before hydration) and by the theme toggle.
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="h-full overflow-hidden">
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
