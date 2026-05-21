"use client";

import { create } from "zustand";

const DEFAULT_API_URL = "http://localhost:8000";

type UserSummary = {
  id: string;
  username: string;
  email: string;
  role: string;
};

type AuthStore = {
  apiKey: string | null;
  apiUrl: string;
  user: UserSummary | null;
  hydrated: boolean;
  hydrate: () => void;
  setCredentials: (apiKey: string, apiUrl: string) => void;
  setUser: (user: UserSummary | null) => void;
  clear: () => void;
};

const KEY_STORAGE = "eta_key";
const URL_STORAGE = "eta_url";

export const useAuthStore = create<AuthStore>((set) => ({
  apiKey: null,
  apiUrl: DEFAULT_API_URL,
  user: null,
  hydrated: false,
  hydrate: () => {
    if (typeof window === "undefined") {
      return;
    }
    const apiKey = window.localStorage.getItem(KEY_STORAGE);
    const apiUrl = window.localStorage.getItem(URL_STORAGE) ?? DEFAULT_API_URL;
    set({ apiKey, apiUrl, hydrated: true });
  },
  setCredentials: (apiKey, apiUrl) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(KEY_STORAGE, apiKey);
      window.localStorage.setItem(URL_STORAGE, apiUrl);
    }
    set({ apiKey, apiUrl });
  },
  setUser: (user) => set({ user }),
  clear: () => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(KEY_STORAGE);
      window.localStorage.removeItem(URL_STORAGE);
    }
    set({ apiKey: null, user: null, apiUrl: DEFAULT_API_URL });
  },
}));
