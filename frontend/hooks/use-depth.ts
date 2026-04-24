"use client";

import { useCallback, useSyncExternalStore } from "react";

export type Depth = "quick" | "standard" | "deep";

const STORAGE_KEY = "ara.depth";
const DEFAULT_DEPTH: Depth = "standard";

const isDepth = (v: unknown): v is Depth =>
  v === "quick" || v === "standard" || v === "deep";

// Module-level subscribe so the useSyncExternalStore identity is stable.
// `storage` events fire for changes in OTHER tabs; same-tab changes are
// broadcast via a custom event in `setDepth`.
const EVENT_NAME = "ara:depth-change";

function subscribe(onChange: () => void): () => void {
  const handler = () => onChange();
  window.addEventListener("storage", handler);
  window.addEventListener(EVENT_NAME, handler);
  return () => {
    window.removeEventListener("storage", handler);
    window.removeEventListener(EVENT_NAME, handler);
  };
}

function getSnapshot(): Depth {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (isDepth(raw)) return raw;
  } catch {
    /* fall through */
  }
  return DEFAULT_DEPTH;
}

function getServerSnapshot(): Depth {
  return DEFAULT_DEPTH;
}

export function useDepth(): {
  depth: Depth;
  setDepth: (d: Depth) => void;
} {
  const depth = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  const setDepth = useCallback((d: Depth) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, d);
    } catch {
      /* swallow quota / disabled storage */
    }
    window.dispatchEvent(new Event(EVENT_NAME));
  }, []);

  return { depth, setDepth };
}
