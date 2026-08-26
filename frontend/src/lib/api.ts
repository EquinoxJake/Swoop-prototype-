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

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
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
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as any;
  const text = await res.text();
  if (!text) return undefined as any;
  return JSON.parse(text);
}

export type User = { user_id: string; email: string; name?: string; picture?: string; created_at: string };
export type AuthResponse = { session_token: string; user: User };

export type PaymentMethod = {
  payment_method_id: string;
  user_id: string;
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  is_default: boolean;
  created_at: string;
};

export type Scooter = {
  scooter_id: string;
  code: string;
  lat: number;
  lng: number;
  battery: number;
  status: "available" | "reserved" | "in_use" | "offline";
  model: string;
  price_per_mile_cents: number;
  unlock_fee_cents: number;
};

export type Ride = {
  ride_id: string;
  user_id: string;
  scooter_id: string;
  scooter_code: string;
  status: "reserved" | "active" | "completed" | "cancelled";
  started_at?: string;
  ended_at?: string;
  minutes: number;
  distance_m: number;
  miles: number;
  unlock_charged_cents: number;
  mileage_charged_cents: number;
  amount_cents: number;
  payment_method_id?: string;
  start_lat?: number;
  start_lng?: number;
  end_lat?: number;
  end_lng?: number;
  route?: number[][];
  paused_seconds?: number;
  created_at: string;
  paid_at?: string;
};

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

  // Payment methods
  listPaymentMethods: () => request<PaymentMethod[]>("/payment-methods"),
  addPaymentMethod: (number: string, exp_month: number, exp_year: number, cvc: string) =>
    request<PaymentMethod>("/payment-methods", {
      method: "POST",
      body: JSON.stringify({ number, exp_month, exp_year, cvc }),
    }),
  deletePaymentMethod: (id: string) =>
    request<{ ok: boolean }>(`/payment-methods/${id}`, { method: "DELETE" }),
  setDefaultPaymentMethod: (id: string) =>
    request<PaymentMethod>(`/payment-methods/${id}/default`, { method: "POST" }),

  // Rides
  reserveRide: (scooter_code: string) =>
    request<Ride>("/rides/reserve", { method: "POST", body: JSON.stringify({ scooter_code }) }),
  startRide: (ride_id: string) =>
    request<Ride>("/rides/start", { method: "POST", body: JSON.stringify({ ride_id }) }),
  endRide: (ride_id: string, distance_m: number, end_lat?: number, end_lng?: number, route?: number[][], paused_seconds?: number) =>
    request<Ride>("/rides/end", {
      method: "POST",
      body: JSON.stringify({ ride_id, end_lat, end_lng, distance_m, route, paused_seconds }),
    }),
  getActiveRide: () => request<Ride | null>("/rides/active"),
  listRides: () => request<Ride[]>("/rides"),
  getRide: (ride_id: string) => request<Ride>(`/rides/${ride_id}`),
};
