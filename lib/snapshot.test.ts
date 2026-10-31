import { describe, expect, it, vi } from "vitest";

import { cv } from "./cv";
import { SNAPSHOT_URL, fetchSnapshot, isCv } from "./snapshot";

const ok = (body: unknown, status = 200) =>
  vi.fn().mockResolvedValue({ ok: status < 300, status, json: async () => body });

describe("isCv", () => {
  it("accepts the bundled CV and rejects anything missing a section", () => {
    expect(isCv(cv)).toBe(true);
    expect(isCv({ ...cv, work: "nope" })).toBe(false);
    expect(isCv({ ...cv, basics: undefined })).toBe(false);
    expect(isCv(null)).toBe(false);
    expect(isCv("x")).toBe(false);
  });
});

describe("fetchSnapshot", () => {
  it("returns the snapshot when it is a valid CV", async () => {
    const f = ok({ ...cv, profile: [] });
    expect((await fetchSnapshot(f))?.profile).toEqual([]);
    expect(f.mock.calls[0][0]).toBe(SNAPSHOT_URL);
    expect(f.mock.calls[0][1]).toMatchObject({ cache: "no-cache" });
  });

  it("falls back (null) on http errors, bad shape, network failure and timeout", async () => {
    expect(await fetchSnapshot(ok({}, 500))).toBeNull();
    expect(await fetchSnapshot(ok({ hello: 1 }))).toBeNull();
    expect(await fetchSnapshot(vi.fn().mockRejectedValue(new Error("offline")))).toBeNull();
    const hang = vi.fn((_u: string, init: { signal: AbortSignal }) =>
      new Promise((_r, rej) => init.signal.addEventListener("abort", () => rej(new Error("aborted")))),
    );
    expect(await fetchSnapshot(hang as never, 20)).toBeNull();
  });

  it("points at the public CloudFront snapshot", () => {
    expect(SNAPSHOT_URL).toMatch(/^https:\/\/.+\/cv\.json$/);
  });
});
