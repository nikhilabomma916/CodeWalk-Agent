"use client";

import { ArrowRight, Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { LogoMark } from "@/components/ui/logo";
import { ThemeToggle } from "@/features/theme/theme-context";

import { LANDING_SECTIONS, SCROLLER_ID } from "./landing-config";

/** Sticky landing navigation: section links with the active one marked, sign-in, and the workspace. */
export function LandingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [active, setActive] = useState<string>("home");
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const scroller = document.getElementById(SCROLLER_ID);
    if (!scroller) return;
    const onScroll = () => setScrolled(scroller.scrollTop > 8);
    onScroll();
    scroller.addEventListener("scroll", onScroll, { passive: true });

    const sections = LANDING_SECTIONS.map((s) => document.getElementById(s.id)).filter(
      (el): el is HTMLElement => el !== null,
    );
    const observer =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver(
            (entries) => {
              const visible = entries.filter((e) => e.isIntersecting);
              if (visible.length > 0) setActive(visible[0].target.id);
            },
            { root: scroller, rootMargin: "-40% 0px -55% 0px" },
          );
    sections.forEach((s) => observer?.observe(s));
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      observer?.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const linkClass = (id: string) =>
    `relative rounded px-2.5 py-1.5 text-[13px] transition-colors ${
      active === id ? "text-fg" : "text-fg-muted hover:text-fg"
    }`;

  return (
    <header
      className={`sticky top-0 z-40 border-b transition-[background-color,border-color] duration-200 ${
        scrolled || menuOpen
          ? "border-border bg-app/85 backdrop-blur-md supports-[backdrop-filter]:bg-app/70"
          : "border-transparent bg-transparent"
      }`}
    >
      <nav
        aria-label="Main"
        className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6"
      >
        <a
          href="#home"
          className="flex items-center gap-2 rounded"
          aria-label="CodeWalk Agent home"
        >
          <LogoMark className="size-5" />
          <span className="text-sm font-semibold tracking-tight text-fg">CodeWalk Agent</span>
        </a>

        <ul className="mx-auto hidden items-center gap-0.5 md:flex">
          {LANDING_SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                aria-current={active === s.id ? "true" : undefined}
                className={linkClass(s.id)}
              >
                {s.label}
                {active === s.id && (
                  <span
                    aria-hidden
                    className="absolute inset-x-2.5 -bottom-[13px] h-px bg-accent"
                  />
                )}
              </a>
            </li>
          ))}
        </ul>

        <div className="ml-auto flex items-center gap-1.5 md:ml-0">
          <ThemeToggle className="size-8" />
          <Link
            href="/login"
            className="hidden rounded px-3 py-1.5 text-[13px] text-fg-muted hover:bg-surface-hover hover:text-fg sm:inline-flex"
          >
            Sign In
          </Link>
          <Link
            href="/app/coding"
            className="group hidden items-center gap-1.5 rounded bg-accent px-3 py-1.5 text-[13px] font-medium text-on-accent transition-colors hover:bg-accent-strong hover:text-on-accent-hover sm:inline-flex"
          >
            Open Workspace
            <ArrowRight
              aria-hidden
              className="size-3.5 transition-transform group-hover:translate-x-0.5"
            />
          </Link>
          <button
            type="button"
            className="inline-flex size-8 items-center justify-center rounded text-fg-muted hover:bg-surface-hover hover:text-fg md:hidden"
            aria-expanded={menuOpen}
            aria-controls="landing-menu"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? (
              <X aria-hidden className="size-4" />
            ) : (
              <Menu aria-hidden className="size-4" />
            )}
          </button>
        </div>
      </nav>

      <div
        id="landing-menu"
        hidden={!menuOpen}
        className="border-t border-border bg-app px-4 pt-2 pb-4 md:hidden"
      >
        <ul className="space-y-0.5">
          {LANDING_SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                onClick={() => setMenuOpen(false)}
                aria-current={active === s.id ? "true" : undefined}
                className={`block rounded px-2 py-2 text-sm ${
                  active === s.id
                    ? "bg-surface-hover text-fg"
                    : "text-fg-muted hover:bg-surface-hover hover:text-fg"
                }`}
              >
                {s.label}
              </a>
            </li>
          ))}
        </ul>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Link
            href="/login"
            className="rounded border border-border px-3 py-2 text-center text-sm text-fg hover:bg-surface-hover"
          >
            Sign In
          </Link>
          <Link
            href="/app/coding"
            className="rounded bg-accent px-3 py-2 text-center text-sm font-medium text-on-accent hover:bg-accent-strong hover:text-on-accent-hover"
          >
            Open Workspace
          </Link>
        </div>
      </div>
    </header>
  );
}
