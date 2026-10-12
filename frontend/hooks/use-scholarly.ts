"use client";

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "ara.scholarly";
const DEFAULT_SCHOLARLY = false;
const EVENT_NAME = "ara:scholarly-change";

function subscribe(onChange: () => void): () => void {
  const handler = () => onChange();
  window.addEventListener("storage", handler);
  window.addEventListener(EVENT_NAME, handler);
  return () => {
    window.removeEventListener("storage", handler);
    window.removeEventListener(EVENT_NAME, handler);
  };
}

function getSnapshot(): boolean {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "true") return true;
    if (raw === "false") return false;
  } catch {
    /* fall through */
  }
  return DEFAULT_SCHOLARLY;
}

function getServerSnapshot(): boolean {
  return DEFAULT_SCHOLARLY;
}

export function useScholarly(): {
  scholarly: boolean;
  setScholarly: (v: boolean) => void;
  toggleScholarly: () => void;
} {
  const scholarly = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  const setScholarly = useCallback((v: boolean) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, String(v));
    } catch {
      /* swallow quota / disabled storage */
    }
    window.dispatchEvent(new Event(EVENT_NAME));
  }, []);

  const toggleScholarly = useCallback(() => {
    setScholarly(!getSnapshot());
  }, [setScholarly]);

  return { scholarly, setScholarly, toggleScholarly };
}
