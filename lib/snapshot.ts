import type { Cv } from "./cv";

// Public CloudFront snapshot published by the MCP; overridable at build time (e.g. the custom domain).
export const SNAPSHOT_URL = process.env.NEXT_PUBLIC_CV_URL ?? "https://d1degxrowcwctx.cloudfront.net/cv.json";

const SECTIONS = ["profile", "work", "education", "projects", "courses", "skills", "languages"] as const;

/** Cheap shape check so a broken or foreign snapshot never replaces the bundled CV. */
export function isCv(value: unknown): value is Cv {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.basics === "object" && v.basics !== null && SECTIONS.every((key) => Array.isArray(v[key]))
  );
}

/** The live CV, or null when the snapshot is unreachable or invalid (callers keep the bundled CV). */
export async function fetchSnapshot(fetchFn: typeof fetch = fetch, timeoutMs = 4000): Promise<Cv | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetchFn(SNAPSHOT_URL, { cache: "no-cache", signal: ctrl.signal });
    if (!res.ok) return null;
    const data: unknown = await res.json();
    return isCv(data) ? data : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
