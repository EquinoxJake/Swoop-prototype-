import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;
const TOKEN_KEY = "swoop_session_token";

async function getStoredToken(): Promise<string | null> {
  if (Platform.OS === "web") {
    try {
      return typeof window !== "undefined" ? window.localStorage.getItem(TOKEN_KEY) : null;
    } catch {
      return null;
    }
  }
  return await SecureStore.getItemAsync(TOKEN_KEY);
}

export async function setToken(token: string | null) {
  if (Platform.OS === "web") {
    if (typeof window !== "undefined") {
      if (token) window.localStorage.setItem(TOKEN_KEY, token);
      else window.localStorage.removeItem(TOKEN_KEY);
    }
    return;
  }
  if (token) await SecureStore.setItemAsync(TOKEN_KEY, token);
  else await SecureStore.deleteItemAsync(TOKEN_KEY);
}

export async function getToken(): Promise<string | null> {
  return getStoredToken();
}

async function request<T>(path: string, opts: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string>),
  };
  if (auth) {
    const token = await getStoredToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${BASE}/api${path}`, { ...opts, headers });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j.detail || msg;
    } catch {}
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as any;
  const text = await res.text();
  if (!text) return undefined as any;
  return JSON.parse(text);
}

// ---- Auth ----
export type User = {
  user_id: string;
  email: string;
  name?: string;
  picture?: string;
  created_at: string;
};

export type AuthResponse = { session_token: string; user: User };

export const api = {
  signup: (email: string, password: string, name?: string) =>
    request<AuthResponse>("/auth/signup", { method: "POST", body: JSON.stringify({ email, password, name }) }, false),
  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, false),
  googleSession: (session_id: string) =>
    request<AuthResponse>("/auth/session", { method: "POST", body: JSON.stringify({ session_id }) }, false),
  me: () => request<User>("/auth/me"),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  // Scooters
  listScooters: () => request<Scooter[]>("/scooters"),
  getScooter: (code: string) => request<Scooter>(`/scooters/${encodeURIComponent(code)}`),
  seedNear: (lat: number, lng: number, radius_m = 500, count = 12) =>
    request<Scooter[]>("/scooters/seed-near", {
      method: "POST",
      body: JSON.stringify({ lat, lng, radius_m, count }),
    }),

  // Rides
  reserveRide: (scooter_code: string) =>
    request<Ride>("/rides/reserve", { method: "POST", body: JSON.stringify({ scooter_code }) }),
  startRide: (ride_id: string) =>
    request<Ride>("/rides/start", { method: "POST", body: JSON.stringify({ ride_id }) }),
  endRide: (ride_id: string, end_lat?: number, end_lng?: number, distance_m?: number) =>
    request<Ride>("/rides/end", {
      method: "POST",
      body: JSON.stringify({ ride_id, end_lat, end_lng, distance_m }),
    }),
  getActiveRide: () => request<Ride | null>("/rides/active"),
  listRides: () => request<Ride[]>("/rides"),
  getRide: (ride_id: string) => request<Ride>(`/rides/${ride_id}`),

  // Payments (MOCKED)
  createMockCheckout: (ride_id: string) =>
    request<MockCheckout>("/payments/mock-checkout", { method: "POST", body: JSON.stringify({ ride_id }) }),
  confirmMockPayment: (ride_id: string) =>
    request<Ride>("/payments/mock-confirm", { method: "POST", body: JSON.stringify({ ride_id }) }),
};

export type Scooter = {
  scooter_id: string;
  code: string;
  lat: number;
  lng: number;
  battery: number;
  status: "available" | "reserved" | "in_use" | "offline";
  model: string;
  price_per_min_cents: number;
  unlock_fee_cents: number;
};

export type Ride = {
  ride_id: string;
  user_id: string;
  scooter_id: string;
  scooter_code: string;
  status: "reserved" | "active" | "awaiting_payment" | "paid" | "cancelled";
  started_at?: string;
  ended_at?: string;
  minutes: number;
  distance_m: number;
  amount_cents: number;
  start_lat?: number;
  start_lng?: number;
  end_lat?: number;
  end_lng?: number;
  created_at: string;
  stripe_session_id?: string;
  paid_at?: string;
};

export type MockCheckout = {
  checkout_url: string;
  session_id: string;
  amount_cents: number;
  minutes: number;
};
