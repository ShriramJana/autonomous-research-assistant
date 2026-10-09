import { describe, expect, it } from "vitest";

import { requestOrigin } from "@/lib/request-origin";

const FALLBACK = "http://0.0.0.0:3000";

function h(obj: Record<string, string>): Headers {
  return new Headers(obj);
}

describe("requestOrigin", () => {
  it("uses forwarded proto + host when present", () => {
    expect(
      requestOrigin(h({ "x-forwarded-proto": "http", "x-forwarded-host": "ara.localtest.me:8088" }), FALLBACK),
    ).toBe("http://ara.localtest.me:8088");
  });
  it("takes the first entry of a comma-separated list", () => {
    expect(
      requestOrigin(h({ "x-forwarded-proto": "https, http", "x-forwarded-host": "a.example, b.example" }), FALLBACK),
    ).toBe("https://a.example");
  });
  it("appends a non-default forwarded port when the host has none", () => {
    expect(
      requestOrigin(h({ "x-forwarded-proto": "http", "x-forwarded-host": "ara.localtest.me", "x-forwarded-port": "8088" }), FALLBACK),
    ).toBe("http://ara.localtest.me:8088");
    expect(
      requestOrigin(h({ "x-forwarded-proto": "https", "x-forwarded-host": "x.example", "x-forwarded-port": "443" }), FALLBACK),
    ).toBe("https://x.example");
  });
  it("does not double the port when the forwarded host already carries it", () => {
    expect(
      requestOrigin(h({ "x-forwarded-proto": "http", "x-forwarded-host": "ara.localtest.me:8088", "x-forwarded-port": "8088" }), FALLBACK),
    ).toBe("http://ara.localtest.me:8088");
  });
  it("falls back to the Host header, then the request url", () => {
    expect(requestOrigin(h({ host: "localhost:3000" }), FALLBACK)).toBe("http://localhost:3000");
    expect(requestOrigin(h({}), FALLBACK)).toBe(FALLBACK);
  });
});
