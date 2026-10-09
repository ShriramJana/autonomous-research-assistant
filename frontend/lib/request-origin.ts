// Origin the browser actually used. Behind the kind ingress the standalone
// Next server sees its own bind address (0.0.0.0:3000); ingress-nginx sends
// the real values in X-Forwarded-* headers.
export function requestOrigin(headers: Headers, fallback: string): string {
  const first = (v: string | null) => (v ? v.split(",")[0].trim() : "");
  const host = first(headers.get("x-forwarded-host")) || first(headers.get("host"));
  if (!host) return fallback;
  const proto = first(headers.get("x-forwarded-proto")) || new URL(fallback).protocol.replace(":", "");
  const port = first(headers.get("x-forwarded-port"));
  const isDefault = (proto === "https" && port === "443") || (proto === "http" && port === "80");
  const hostWithPort = port && !host.includes(":") && !isDefault ? `${host}:${port}` : host;
  return `${proto}://${hostWithPort}`;
}
