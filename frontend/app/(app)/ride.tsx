import { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Modal,
  Platform,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, Ride } from "@/src/lib/api";
import { colors, spacing, radius, shadow } from "@/src/lib/theme";

type BleStep = "idle" | "searching" | "connecting" | "unlocking" | "connected" | "error";

export default function RideScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { ride_id } = useLocalSearchParams<{ ride_id: string }>();

  const [ride, setRide] = useState<Ride | null>(null);
  const [ble, setBle] = useState<BleStep>("searching");
  const [showBleModal, setShowBleModal] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const [distance, setDistance] = useState(0);
  const [ending, setEnding] = useState(false);
  const timerRef = useRef<any>(null);

  // Load ride
  useEffect(() => {
    if (!ride_id) return;
    (async () => {
      try {
        const r = await api.getRide(ride_id);
        setRide(r);
      } catch (e) {
        console.warn(e);
      }
    })();
  }, [ride_id]);

  // BLE simulation
  useEffect(() => {
    if (!ride) return;
    if (ride.status === "active") { setBle("connected"); setShowBleModal(false); return; }
    if (ride.status !== "reserved") return;

    let cancelled = false;
    (async () => {
      setBle("searching");
      await sleep(1100);
      if (cancelled) return;
      setBle("connecting");
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      await sleep(1200);
      if (cancelled) return;
      setBle("unlocking");
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      await sleep(1400);
      if (cancelled) return;
      try {
        const r = await api.startRide(ride.ride_id);
        setRide(r);
        setBle("connected");
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        await sleep(700);
        if (!cancelled) setShowBleModal(false);
      } catch (e) {
        setBle("error");
      }
    })();
    return () => { cancelled = true; };
  }, [ride?.ride_id, ride?.status]);

  // Ride timer + distance sim
  useEffect(() => {
    if (!ride || ride.status !== "active" || !ride.started_at) return;
    const start = new Date(ride.started_at).getTime();
    const tick = () => {
      const now = Date.now();
      const secs = Math.floor((now - start) / 1000);
      setElapsed(secs);
      // simulate ~4.5 m/s (10 mph) average
      setDistance(Math.round(secs * 4.5));
    };
    tick();
    timerRef.current = setInterval(tick, 1000);
    return () => clearInterval(timerRef.current);
  }, [ride?.status, ride?.started_at]);

  const price = ride ? (100 + Math.max(1, Math.ceil(elapsed / 60)) * 35) / 100 : 0;

  const onEnd = async () => {
    if (!ride) return;
    setEnding(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    try {
      const updated = await api.endRide(ride.ride_id, undefined, undefined, distance);
      router.replace(`/(app)/receipt?ride_id=${updated.ride_id}`);
    } catch (e: any) {
      alert(e.message || "Failed to end ride");
    } finally {
      setEnding(false);
    }
  };

  if (!ride) {
    return (
      <View style={styles.loadingScreen}>
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  return (
    <View style={styles.container} testID="ride-screen">
      {/* Ambient dimmed background */}
      <View style={styles.mapBg} />

      {/* Top status bar */}
      <View style={[styles.topBar, { top: insets.top + spacing.md }]}>
        <View style={styles.statusPill}>
          <View style={styles.pulse} />
          <Text style={styles.statusText}>Riding · {ride.scooter_code}</Text>
        </View>
      </View>

      {/* Metrics sheet */}
      <View style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]}>
        <View style={styles.metricsWrap}>
          <View style={styles.timerBox}>
            <Text style={styles.timerLabel}>Time</Text>
            <Text style={styles.timerText} testID="ride-timer">{formatTime(elapsed)}</Text>
          </View>

          <View style={styles.smallMetrics}>
            <View style={styles.smallMetric}>
              <Ionicons name="map-outline" size={18} color={colors.muted} />
              <Text style={styles.smallValue} testID="ride-distance">
                {(distance / 1609).toFixed(2)} mi
              </Text>
              <Text style={styles.smallLabel}>Distance</Text>
            </View>
            <View style={styles.divider} />
            <View style={styles.smallMetric}>
              <Ionicons name="pricetag-outline" size={18} color={colors.muted} />
              <Text style={styles.smallValue} testID="ride-cost">${price.toFixed(2)}</Text>
              <Text style={styles.smallLabel}>Running cost</Text>
            </View>
          </View>
        </View>

        <Pressable
          testID="end-ride-button"
          onPress={onEnd}
          disabled={ending || ride.status !== "active"}
          style={({ pressed }) => [styles.endBtn, pressed && { opacity: 0.85 }, ending && { opacity: 0.6 }]}
        >
          {ending ? (
            <ActivityIndicator color={colors.onSurfaceInverse} />
          ) : (
            <>
              <Ionicons name="stop-circle" size={24} color={colors.onSurfaceInverse} />
              <Text style={styles.endText}>End ride</Text>
            </>
          )}
        </Pressable>
      </View>

      {/* BLE Modal */}
      <Modal visible={showBleModal} transparent animationType="fade">
        <View style={styles.modalBg}>
          <View style={styles.modalCard} testID="ble-modal">
            <View style={styles.blePulse}>
              <Ionicons name="bluetooth" size={40} color={colors.brand} />
            </View>
            <Text style={styles.modalTitle}>
              {ble === "searching" && "Finding scooter…"}
              {ble === "connecting" && "Connecting…"}
              {ble === "unlocking" && "Unlocking scooter…"}
              {ble === "connected" && "Unlocked! Ride safe."}
              {ble === "error" && "Connection failed"}
            </Text>
            <Text style={styles.modalSub}>
              {ble === "connected"
                ? "Kick off to start moving."
                : ble === "error"
                ? "Please try again"
                : "Simulated BLE handshake (MOCKED)"}
            </Text>
            {ble !== "connected" && ble !== "error" && (
              <ActivityIndicator size="small" color={colors.brand} style={{ marginTop: spacing.md }} />
            )}
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
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  loadingScreen: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  mapBg: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.surfaceTertiary },
  topBar: { position: "absolute", left: spacing.lg, right: spacing.lg, alignItems: "center" },
  statusPill: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceInverse,
    paddingHorizontal: spacing.lg, paddingVertical: 10,
    borderRadius: radius.pill,
    ...shadow.card,
  },
  pulse: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandSecondary },
  statusText: { color: colors.onSurfaceInverse, fontWeight: "800", fontSize: 13 },

  sheet: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: colors.surfaceSecondary,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.lg,
    ...shadow.floating,
  },
  metricsWrap: { gap: spacing.md },
  timerBox: {
    backgroundColor: colors.brand,
    borderRadius: radius.lg,
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
  },
  timerLabel: { color: colors.onBrandPrimary, fontWeight: "700", opacity: 0.7, fontSize: 12, letterSpacing: 1, textTransform: "uppercase" },
  timerText: {
    color: colors.onBrandPrimary,
    fontSize: 72, fontWeight: "800", letterSpacing: -2, marginTop: 4,
    fontVariant: ["tabular-nums"],
  },
  smallMetrics: {
    flexDirection: "row",
    backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.md,
    padding: spacing.lg,
  },
  smallMetric: { flex: 1, alignItems: "center", gap: 4 },
  smallValue: { fontSize: 22, fontWeight: "800", color: colors.onSurface, fontVariant: ["tabular-nums"] },
  smallLabel: { fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  divider: { width: 1, backgroundColor: colors.border },
  endBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceInverse, borderRadius: radius.pill, paddingVertical: 20,
  },
  endText: { color: colors.onSurfaceInverse, fontWeight: "800", fontSize: 17 },

  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center", padding: spacing.xl },
  modalCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.xxl,
    alignItems: "center",
    width: "100%",
    maxWidth: 360,
    gap: spacing.sm,
  },
  blePulse: {
    width: 90, height: 90, borderRadius: 45,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
    marginBottom: spacing.md,
  },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.onSurface, textAlign: "center" },
  modalSub: { fontSize: 13, color: colors.muted, textAlign: "center" },
  modalBtn: {
    backgroundColor: colors.brand, paddingHorizontal: spacing.xl, paddingVertical: 14,
    borderRadius: radius.pill, marginTop: spacing.md,
  },
  modalBtnText: { color: colors.onBrandPrimary, fontWeight: "800" },
});
