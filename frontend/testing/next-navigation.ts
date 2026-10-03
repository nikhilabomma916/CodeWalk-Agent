/**
 * A controllable stand-in for `next/navigation` in component tests:
 *
 *   vi.mock("next/navigation", () => import("@/testing/next-navigation"));
 *
 * then set `navigation.pathname` / `navigation.search` before rendering and
 * assert on `navigation.router.replace` / `push`.
 */
import { vi } from "vitest";

export const navigation = {
  pathname: "/",
  search: "",
  router: {
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  },
  reset(pathname = "/", search = "") {
    this.pathname = pathname;
    this.search = search;
    Object.values(this.router).forEach((fn) => fn.mockReset());
  },
};

export function useRouter() {
  return navigation.router;
}

export function usePathname() {
  return navigation.pathname;
}

export function useSearchParams() {
  return new URLSearchParams(navigation.search);
}

export function useParams() {
  return {};
}

export function redirect(path: string): never {
  throw new Error(`redirect(${path})`);
}
