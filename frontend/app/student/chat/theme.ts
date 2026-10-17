"use client";

import { useSyncExternalStore } from "react";

type Theme = "light" | "dark";
const preferenceKey = "rantau-theme";
const preferenceEvent = "rantau-theme-change";
let memoryPreference: Theme | undefined;

function snapshot(): Theme {
  if (memoryPreference) return memoryPreference;
  try {
    const saved = localStorage.getItem(preferenceKey);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* A blocked preference store must not disable the control. */ }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function subscribe(notify: () => void) {
  const media = matchMedia("(prefers-color-scheme: dark)");
  const storageChanged = () => { memoryPreference = undefined; notify(); };
  media.addEventListener("change", notify);
  window.addEventListener("storage", storageChanged);
  window.addEventListener(preferenceEvent, notify);
  return () => {
    media.removeEventListener("change", notify);
    window.removeEventListener("storage", storageChanged);
    window.removeEventListener(preferenceEvent, notify);
  };
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, snapshot, (): Theme | "system" => "system");
  return {
    theme,
    toggleTheme() {
      const next = snapshot() === "dark" ? "light" : "dark";
      memoryPreference = next;
      try { localStorage.setItem(preferenceKey, next); } catch { /* Keep this session's choice. */ }
      window.dispatchEvent(new Event(preferenceEvent));
    },
  };
}
