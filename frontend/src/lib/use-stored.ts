"use client";

import { useCallback, useSyncExternalStore } from "react";

const EVENT = "attest:storage";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // private mode / blocked storage: behave as empty
  }
}

/**
 * A per-browser preference in localStorage (sidebar state, recent uploads).
 * Server render and first paint see `null`, so there is no hydration mismatch.
 */
export function useStored(key: string): [string | null, (value: string) => void] {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const handler = (e: Event) => {
        if (!(e instanceof StorageEvent) || e.key === key) onChange();
      };
      window.addEventListener("storage", handler);
      window.addEventListener(EVENT, handler);
      return () => {
        window.removeEventListener("storage", handler);
        window.removeEventListener(EVENT, handler);
      };
    },
    [key],
  );
  const value = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );
  const set = useCallback(
    (next: string) => {
      try {
        localStorage.setItem(key, next);
      } catch {}
      window.dispatchEvent(new Event(EVENT));
    },
    [key],
  );
  return [value, set];
}
