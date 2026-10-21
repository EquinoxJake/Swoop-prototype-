import React, { createContext, useContext, useEffect, useState } from "react";
import * as WebBrowser from "expo-web-browser";
import * as Google from "expo-auth-session/providers/google";
import { api, setToken, getToken, User } from "./api";

WebBrowser.maybeCompleteAuthSession();

// OAuth client IDs from Google Cloud Console (one per platform)
const googleClientIds = {
  webClientId: process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID,
  iosClientId: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID,
  androidClientId: process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID,
};

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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [, , promptGoogle] = Google.useIdTokenAuthRequest(googleClientIds);

  // On mount: restore an existing session
  useEffect(() => {
    (async () => {
      try {
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

  // Google returns an ID token; the backend verifies it and gives us our own session token
  const signInWithGoogle = async () => {
    const result = await promptGoogle();
    if (result.type !== "success") throw new Error("Google sign-in was cancelled");
    const idToken = result.params.id_token;
    if (!idToken) throw new Error("Google did not return an ID token");
    const res = await api.googleSignIn(idToken);
    await setToken(res.session_token);
    setUser(res.user);
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
