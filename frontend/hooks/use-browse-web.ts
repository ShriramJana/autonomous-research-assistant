"use client";

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "ara.browse_web";
const DEFAULT_BROWSE_WEB = true;
const EVENT_NAME = "ara:browse-web-change";

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
  return DEFAULT_BROWSE_WEB;
}

function getServerSnapshot(): boolean {
  return DEFAULT_BROWSE_WEB;
}

export function useBrowseWeb(): {
  browseWeb: boolean;
  setBrowseWeb: (v: boolean) => void;
  toggleBrowseWeb: () => void;
} {
  const browseWeb = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  const setBrowseWeb = useCallback((v: boolean) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, String(v));
    } catch {
      /* swallow quota / disabled storage */
    }
    window.dispatchEvent(new Event(EVENT_NAME));
  }, []);

  const toggleBrowseWeb = useCallback(() => {
    setBrowseWeb(!getSnapshot());
  }, [setBrowseWeb]);

  return { browseWeb, setBrowseWeb, toggleBrowseWeb };
}
