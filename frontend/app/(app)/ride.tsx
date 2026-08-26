import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Modal, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import * as Location from "expo-location";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, Ride } from "@/src/lib/api";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

type BleStep = "idle" | "searching" | "connecting" | "unlocking" | "connected" | "error";

const METERS_PER_MILE = 1609.344;
const UNLOCK_CENTS = 100;
const PER_MILE_CENTS = 20;

function haversineMeters(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const R = 6371000;
  const p1 = (a.lat * Math.PI) / 180;
  const p2 = (b.lat * Math.PI) / 180;
  const dp = ((b.lat - a.lat) * Math.PI) / 180;
  const dl = ((b.lng - a.lng) * Math.PI) / 180;
  const c = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(c));
}

export default function RideScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { colors } = useTheme();
  const { ride_id } = useLocalSearchParams<{ ride_id: string }>();
  const [ride, setRide] = useState<Ride | null>(null);
  const [ble, setBle] = useState<BleStep>("searching");
  const [showBleModal, setShowBleModal] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const [distanceM, setDistanceM] = useState(0);
  const [gpsAvailable, setGpsAvailable] = useState<boolean | null>(null);
  const [ending, setEnding] = useState(false);
  const [paused, setPaused] = useState(false);
  const [pausedSeconds, setPausedSeconds] = useState(0);
  const lastPos = useRef<{ lat: number; lng: number } | null>(null);
  const lastCoords = useRef<{ lat: number; lng: number } | null>(null);
  const lastMovedAtRef = useRef<number>(Date.now());
  const routeRef = useRef<number[][]>([]);
  const pausedAccumRef = useRef<number>(0);
  const pausedStartRef = useRef<number | null>(null);
  const timerRef = useRef<any>(null);
  const idleCheckRef = useRef<any>(null);
  const watchSub = useRef<Location.LocationSubscription | null>(null);
  const styles = useMemo(() => makeStyles(colors), [colors]);

  useEffect(() => {
    if (!ride_id) return;
    (async () => { try { const r = await api.getRide(ride_id); setRide(r); } catch (e) { console.warn(e); } })();
  }, [ride_id]);

  // BLE simulation → active
  useEffect(() => {
    if (!ride) return;
    if (ride.status === "active") { setBle("connected"); setShowBleModal(false); return; }
    if (ride.status !== "reserved") return;
    let cancelled = false;
    (async () => {
      setBle("searching"); await sleep(1100); if (cancelled) return;
      setBle("connecting"); Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); await sleep(1200); if (cancelled) return;
      setBle("unlocking"); Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium); await sleep(1400); if (cancelled) return;
      try {
        const r = await api.startRide(ride.ride_id); setRide(r); setBle("connected");
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        await sleep(700); if (!cancelled) setShowBleModal(false);
      } catch (e) { setBle("error"); }
    })();
    return () => { cancelled = true; };
  }, [ride?.ride_id, ride?.status]);

  // GPS tracking during active ride
  useEffect(() => {
    if (!ride || ride.status !== "active") return;
    let cancelled = false;
    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== "granted") { setGpsAvailable(false); return; }
        setGpsAvailable(true);
        const first = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
        if (cancelled) return;
        const p0 = { lat: first.coords.latitude, lng: first.coords.longitude };
        lastPos.current = p0;
        lastCoords.current = p0;
        routeRef.current.push([p0.lat, p0.lng]);
        lastMovedAtRef.current = Date.now();
        watchSub.current = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.High, distanceInterval: 3, timeInterval: 1000 },
          (loc) => {
            const cur = { lat: loc.coords.latitude, lng: loc.coords.longitude };
            if (lastPos.current) {
              const step = haversineMeters(lastPos.current, cur);
              // Ignore GPS jitter <2m and unrealistic >300m jumps between samples
              if (step >= 2 && step < 300) {
                setDistanceM((d) => d + step);
                lastMovedAtRef.current = Date.now();
                routeRef.current.push([cur.lat, cur.lng]);
                // Coming out of a pause
                if (pausedStartRef.current !== null) {
                  pausedAccumRef.current += Math.floor((Date.now() - pausedStartRef.current) / 1000);
                  pausedStartRef.current = null;
                  setPaused(false);
                }
              }
            }
            lastPos.current = cur;
            lastCoords.current = cur;
          },
        );
      } catch (e) { setGpsAvailable(false); }
    })();
    return () => { cancelled = true; watchSub.current?.remove(); watchSub.current = null; };
  }, [ride?.status]);

  // Auto-pause detector: if no movement for 60s, mark paused
  useEffect(() => {
    if (!ride || ride.status !== "active") return;
    idleCheckRef.current = setInterval(() => {
      const idleSecs = Math.floor((Date.now() - lastMovedAtRef.current) / 1000);
      if (idleSecs >= 60 && pausedStartRef.current === null) {
        pausedStartRef.current = Date.now() - 60_000; // count from when they stopped moving
        setPaused(true);
        Haptics.selectionAsync();
      }
      // Update live paused seconds counter
      if (pausedStartRef.current !== null) {
        const live = pausedAccumRef.current + Math.floor((Date.now() - pausedStartRef.current) / 1000);
        setPausedSeconds(live);
      } else {
        setPausedSeconds(pausedAccumRef.current);
      }
    }, 1000);
    return () => clearInterval(idleCheckRef.current);
  }, [ride?.status]);

  // Ride timer
  useEffect(() => {
    if (!ride || ride.status !== "active" || !ride.started_at) return;
    const start = new Date(ride.started_at).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - start) / 1000));
    tick(); timerRef.current = setInterval(tick, 1000);
    return () => clearInterval(timerRef.current);
  }, [ride?.status, ride?.started_at]);

  const miles = distanceM / METERS_PER_MILE;
  const mileageCents = Math.max(0, Math.ceil(miles * PER_MILE_CENTS));
  const totalCents = UNLOCK_CENTS + mileageCents;

  const onEnd = async () => {
    if (!ride) return;
    setEnding(true); Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    watchSub.current?.remove(); watchSub.current = null;
    clearInterval(idleCheckRef.current);
    // Finalize pause accumulator
    let totalPaused = pausedAccumRef.current;
    if (pausedStartRef.current !== null) {
      totalPaused += Math.floor((Date.now() - pausedStartRef.current) / 1000);
    }
    const endLat = lastCoords.current?.lat;
    const endLng = lastCoords.current?.lng;
    const params = new URLSearchParams({
      ride_id: ride.ride_id,
      distance_m: String(Math.round(distanceM)),
      paused_seconds: String(totalPaused),
      route_json: JSON.stringify(routeRef.current),
    });
    if (endLat !== undefined) params.set("end_lat", String(endLat));
    if (endLng !== undefined) params.set("end_lng", String(endLng));
    router.replace(`/(app)/parking-check?${params.toString()}`);
    setEnding(false);
  };

  if (!ride) {
    return <View style={styles.loadingScreen}><ActivityIndicator size="large" color={colors.brand} /></View>;
  }

  return (
    <View style={styles.container} testID="ride-screen">
      <View style={styles.mapBg} />
      <View style={[styles.topBar, { top: insets.top + spacing.md }]}>
        <View style={styles.statusPill}>
          <View style={[styles.pulse, paused && { backgroundColor: colors.warning }]} />
          <Text style={styles.statusText}>{paused ? `Paused · ${ride.scooter_code}` : `Riding · ${ride.scooter_code}`}</Text>
        </View>
        {paused && (
          <View style={[styles.statusPill, { marginTop: spacing.sm, backgroundColor: colors.warning }]}>
            <Ionicons name="pause-circle" size={14} color={colors.onWarning} />
            <Text style={[styles.statusText, { color: colors.onWarning }]}>
              Not moving — you won't be charged
            </Text>
          </View>
        )}
        {gpsAvailable === false && (
          <View style={[styles.statusPill, { marginTop: spacing.sm, backgroundColor: colors.warning }]}>
            <Ionicons name="warning" size={14} color={colors.onWarning} />
            <Text style={[styles.statusText, { color: colors.onWarning }]}>GPS off — distance won't track</Text>
          </View>
        )}
      </View>

      <View style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]}>
        <View style={styles.metricsWrap}>
          <View style={styles.timerBox}>
            <Text style={styles.timerLabel}>Time</Text>
            <Text style={styles.timerText} testID="ride-timer">{formatTime(elapsed)}</Text>
          </View>
          <View style={styles.smallMetrics}>
            <View style={styles.smallMetric}>
              <Ionicons name="location-outline" size={18} color={colors.muted} />
              <Text style={styles.smallValue} testID="ride-distance">{miles.toFixed(2)} mi</Text>
              <Text style={styles.smallLabel}>GPS distance</Text>
            </View>
            <View style={styles.divider} />
            <View style={styles.smallMetric}>
              <Ionicons name="cash-outline" size={18} color={colors.muted} />
              <Text style={styles.smallValue} testID="ride-cost">${(totalCents / 100).toFixed(2)}</Text>
              <Text style={styles.smallLabel}>$1 + $0.20/mi</Text>
            </View>
          </View>
        </View>
        <Pressable testID="end-ride-button" onPress={onEnd} disabled={ending || ride.status !== "active"} style={({ pressed }) => [styles.endBtn, pressed && { opacity: 0.85 }, ending && { opacity: 0.6 }]}>
          {ending ? <ActivityIndicator color={colors.onSurfaceInverse} /> : (
            <>
              <Ionicons name="stop-circle" size={24} color={colors.onSurfaceInverse} />
              <Text style={styles.endText}>End ride</Text>
            </>
          )}
        </Pressable>
      </View>

      <Modal visible={showBleModal} transparent animationType="fade">
        <View style={styles.modalBg}>
          <View style={styles.modalCard} testID="ble-modal">
            <View style={styles.blePulse}><Ionicons name="bluetooth" size={40} color={colors.brand} /></View>
            <Text style={styles.modalTitle}>
              {ble === "searching" && "Finding scooter…"}
              {ble === "connecting" && "Connecting…"}
              {ble === "unlocking" && "Unlocking scooter…"}
              {ble === "connected" && "Unlocked! Ride safe."}
              {ble === "error" && "Connection failed"}
            </Text>
            <Text style={styles.modalSub}>
              {ble === "connected" ? "$1.00 unlock fee charged. Mileage will be billed as you ride." : ble === "error" ? "Please try again" : "Simulated BLE handshake (MOCKED)"}
            </Text>
            {ble !== "connected" && ble !== "error" && <ActivityIndicator size="small" color={colors.brand} style={{ marginTop: spacing.md }} />}
            {ble === "error" && (
              <Pressable onPress={() => router.back()} style={styles.modalBtn} testID="ble-back-button">
                <Text style={styles.modalBtnText}>Go back</Text>
              </Pressable>
            )}
          </View>
        </View>
      </Modal>
    </View>
  );
}

function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }
function formatTime(secs: number): string {
  const m = Math.floor(secs / 60); const s = secs % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

const makeStyles = (c: any) => StyleSheet.create({
  container: { flex: 1, backgroundColor: c.surface },
  loadingScreen: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.surface },
  mapBg: { ...StyleSheet.absoluteFillObject, backgroundColor: c.surfaceTertiary },
  topBar: { position: "absolute", left: spacing.lg, right: spacing.lg, alignItems: "center" },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surfaceInverse, paddingHorizontal: spacing.lg, paddingVertical: 10, borderRadius: radius.pill, ...shadow.card },
  pulse: { width: 8, height: 8, borderRadius: 4, backgroundColor: c.brandSecondary },
  statusText: { color: c.onSurfaceInverse, fontWeight: "800", fontSize: 13 },
  sheet: { position: "absolute", left: 0, right: 0, bottom: 0, backgroundColor: c.surfaceSecondary, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.xl, gap: spacing.lg, ...shadow.floating },
  metricsWrap: { gap: spacing.md },
  timerBox: { backgroundColor: c.brand, borderRadius: radius.lg, paddingVertical: spacing.xl, paddingHorizontal: spacing.lg, alignItems: "center" },
  timerLabel: { color: c.onBrandPrimary, fontWeight: "700", opacity: 0.7, fontSize: 12, letterSpacing: 1, textTransform: "uppercase" },
  timerText: { color: c.onBrandPrimary, fontSize: 72, fontWeight: "800", letterSpacing: -2, marginTop: 4, fontVariant: ["tabular-nums"] },
  smallMetrics: { flexDirection: "row", backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.lg },
  smallMetric: { flex: 1, alignItems: "center", gap: 4 },
  smallValue: { fontSize: 22, fontWeight: "800", color: c.onSurface, fontVariant: ["tabular-nums"] },
  smallLabel: { fontSize: 11, color: c.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  divider: { width: 1, backgroundColor: c.border },
  endBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: c.surfaceInverse, borderRadius: radius.pill, paddingVertical: 20 },
  endText: { color: c.onSurfaceInverse, fontWeight: "800", fontSize: 17 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center", padding: spacing.xl },
  modalCard: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xxl, alignItems: "center", width: "100%", maxWidth: 360, gap: spacing.sm },
  blePulse: { width: 90, height: 90, borderRadius: 45, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center", marginBottom: spacing.md },
  modalTitle: { fontSize: 20, fontWeight: "800", color: c.onSurface, textAlign: "center" },
  modalSub: { fontSize: 13, color: c.muted, textAlign: "center" },
  modalBtn: { backgroundColor: c.brand, paddingHorizontal: spacing.xl, paddingVertical: 14, borderRadius: radius.pill, marginTop: spacing.md },
  modalBtnText: { color: c.onBrandPrimary, fontWeight: "800" },
});
