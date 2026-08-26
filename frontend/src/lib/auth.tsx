import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { Platform } from "react-native";
import { api, setToken, getToken, User } from "./api";

WebBrowser.maybeCompleteAuthSession();

type AuthState = {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name?: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthCtx = createContext<AuthState | undefined>(undefined);

const processedSessionIds = new Set<string>();

function extractSessionId(url: string | null | undefined): string | null {
  if (!url) return null;
  const m = url.match(/[?#&]session_id=([^&#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const exchangeSessionId = useCallback(async (sid: string) => {
    if (processedSessionIds.has(sid)) return;
    processedSessionIds.add(sid);
    try {
      const res = await api.googleSession(sid);
      await setToken(res.session_token);
      setUser(res.user);
    } catch (e) {
      console.warn("Google session exchange failed", e);
    }
  }, []);

  // On mount: check for existing session, check deep-link for session_id
  useEffect(() => {
    let sub: any;
    (async () => {
      try {
        // Web: check URL for session_id
        if (Platform.OS === "web" && typeof window !== "undefined") {
          const sid = extractSessionId(window.location.hash) || extractSessionId(window.location.search);
          if (sid) {
            await exchangeSessionId(sid);
            // Clean the URL
            try {
              const clean = window.location.href.replace(/[?#&]session_id=[^&#]+/, "");
              window.history.replaceState(window.history.state, "", clean);
            } catch {}
          }
        } else {
          const initial = await Linking.getInitialURL();
          const sid = extractSessionId(initial);
          if (sid) await exchangeSessionId(sid);
          sub = Linking.addEventListener("url", (ev) => {
            const s = extractSessionId(ev.url);
            if (s) exchangeSessionId(s);
          });
        }

        // If we already have a token, load user
        const token = await getToken();
        if (token && !user) {
          try {
            const me = await api.me();
            setUser(me);
          } catch {
            await setToken(null);
          }
        }
      } finally {
        setLoading(false);
      }
    })();
    return () => sub?.remove?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const signIn = async (email: string, password: string) => {
    const res = await api.login(email, password);
    await setToken(res.session_token);
    setUser(res.user);
  };

  const signUp = async (email: string, password: string, name?: string) => {
    const res = await api.signup(email, password, name);
    await setToken(res.session_token);
    setUser(res.user);
  };

  const signInWithGoogle = async () => {
    const redirect = Platform.OS === "web"
      ? (typeof window !== "undefined" ? window.location.origin + "/" : "")
      : Linking.createURL("");
    const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirect)}`;
    if (Platform.OS === "web") {
      window.location.href = authUrl;
      return;
    }
    // Register listener FIRST
    let captured: string | null = null;
    const listener = Linking.addEventListener("url", (ev) => {
      const s = extractSessionId(ev.url);
      if (s) captured = s;
    });
    try {
      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirect);
      let sid: string | null = null;
      if (result.type === "success" && (result as any).url) {
        sid = extractSessionId((result as any).url);
      }
      if (!sid && captured) sid = captured;
      if (!sid) {
        const initial = await Linking.getInitialURL();
        sid = extractSessionId(initial);
      }
      if (sid) await exchangeSessionId(sid);
    } finally {
      listener.remove();
    }
  };

  const signOut = async () => {
    try {
      await api.logout();
    } catch {}
    await setToken(null);
    setUser(null);
  };

  const refresh = async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch {
      setUser(null);
    }
  };

  return (
    <AuthCtx.Provider value={{ user, loading, signIn, signUp, signInWithGoogle, signOut, refresh }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be within AuthProvider");
  return ctx;
}
