const KEY = "ara.anthropic_key";

export function getStoredApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function setStoredApiKey(value: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, value);
}

export function clearStoredApiKey(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}

export function hasStoredApiKey(): boolean {
  return getStoredApiKey() !== null;
}
