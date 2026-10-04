import type { MetadataRoute } from "next";

/** The public landing page is indexable; the signed-in application is not. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/app/"] }],
  };
}
