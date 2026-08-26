import { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, Ride } from "@/src/lib/api";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

type Phase = "review" | "processing" | "paid" | "error";

export default function Receipt() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { colors } = useTheme();
  const { ride_id } = useLocalSearchParams<{ ride_id: string }>();
  const [ride, setRide] = useState<Ride | null>(null);
  const [phase, setPhase] = useState<Phase>("review");
  const [err, setErr] = useState<string | null>(null);
  const styles = useMemo(() => makeStyles(colors), [colors]);

  useEffect(() => {
    if (!ride_id) return;
    (async () => {
      try { const r = await api.getRide(ride_id); setRide(r); if (r.status === "paid") setPhase("paid"); }
      catch (e: any) { setErr(e.message); }
    })();
  }, [ride_id]);

  const onPay = async () => {
    if (!ride) return;
    setPhase("processing"); Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      await api.createMockCheckout(ride.ride_id);
      await new Promise(r => setTimeout(r, 1400));
      const paid = await api.confirmMockPayment(ride.ride_id);
      setRide(paid); setPhase("paid");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (e: any) { setErr(e.message || "Payment failed"); setPhase("error"); }
  };

  if (!ride) return <View style={styles.loading}><ActivityIndicator color={colors.brand} size="large" /></View>;

  const dollars = (ride.amount_cents / 100).toFixed(2);
  const unlockDollars = (100 / 100).toFixed(2);
  const rideMinDollars = ((ride.amount_cents - 100) / 100).toFixed(2);

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }} testID="receipt-screen">
      <ScrollView contentContainerStyle={[styles.container, { paddingTop: insets.top + spacing.xxl, paddingBottom: insets.bottom + spacing.xxl }]}>
        <View style={styles.header}>
          <View style={[styles.badge, { backgroundColor: phase === "paid" ? colors.brandSecondary : colors.brand }]}>
            <Ionicons name={phase === "paid" ? "checkmark" : "receipt"} size={28} color={phase === "paid" ? colors.onBrandSecondary : colors.onBrandPrimary} />
          </View>
          <Text style={styles.title}>{phase === "paid" ? "Ride complete!" : "Trip summary"}</Text>
          <Text style={styles.sub}>{phase === "paid" ? "Thanks for riding Swoop" : `Scooter ${ride.scooter_code}`}</Text>
        </View>

        <View style={styles.card}>
          <Row label="Duration" value={`${ride.minutes} min`} styles={styles} />
          <Row label="Distance" value={`${(ride.distance_m / 1609).toFixed(2)} mi`} styles={styles} />
          <Row label="Scooter" value={ride.scooter_code} styles={styles} />
          <View style={styles.hr} />
          <Row label="Unlock fee" value={`$${unlockDollars}`} muted styles={styles} colors={colors} />
          <Row label={`Riding (${ride.minutes} min × $0.35)`} value={`$${rideMinDollars}`} muted styles={styles} colors={colors} />
          <View style={styles.hr} />
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalValue} testID="receipt-total">${dollars}</Text>
          </View>
        </View>

        {phase === "review" && (
          <>
            <View style={styles.methodCard}>
              <View style={styles.methodRow}>
                <Ionicons name="card-outline" size={22} color={colors.onSurface} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.methodTitle}>Stripe (test mode)</Text>
                  <Text style={styles.methodSub}>MOCKED — no real charge</Text>
                </View>
                <Ionicons name="checkmark-circle" size={22} color={colors.brandSecondary} />
              </View>
            </View>
            <Pressable testID="pay-button" onPress={onPay} style={({ pressed }) => [styles.primary, pressed && { opacity: 0.9 }]}>
              <Text style={styles.primaryText}>Pay ${dollars}</Text>
            </Pressable>
          </>
        )}

        {phase === "processing" && (
          <View style={styles.processing}>
            <ActivityIndicator color={colors.brand} size="large" />
            <Text style={styles.processingText}>Processing payment…</Text>
          </View>
        )}

        {phase === "paid" && (
          <Pressable testID="done-button" onPress={() => router.replace("/(app)/map")} style={({ pressed }) => [styles.primary, pressed && { opacity: 0.9 }]}>
            <Text style={styles.primaryText}>Done</Text>
          </Pressable>
        )}

        {phase === "error" && (
          <>
            {err && <Text style={styles.error} testID="receipt-error">{err}</Text>}
            <Pressable onPress={onPay} style={styles.primary}><Text style={styles.primaryText}>Try again</Text></Pressable>
          </>
        )}
      </ScrollView>
    </View>
  );
}

function Row({ label, value, muted, styles, colors }: any) {
  return (
    <View style={styles.row}>
      <Text style={[styles.rowLabel, muted && { color: colors?.muted }]}>{label}</Text>
      <Text style={[styles.rowValue, muted && { color: colors?.muted, fontWeight: "600" }]}>{value}</Text>
    </View>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  loading: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.surface },
  container: { padding: spacing.xl, gap: spacing.lg },
  header: { alignItems: "center", gap: spacing.sm, marginBottom: spacing.md },
  badge: { width: 68, height: 68, borderRadius: 34, alignItems: "center", justifyContent: "center", ...shadow.card },
  title: { fontSize: 28, fontWeight: "800", color: c.onSurface, letterSpacing: -0.5 },
  sub: { color: c.muted, fontSize: 14 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl, gap: spacing.sm, ...shadow.card },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 6 },
  rowLabel: { color: c.onSurface, fontSize: 14 },
  rowValue: { color: c.onSurface, fontSize: 14, fontWeight: "700" },
  hr: { height: 1, backgroundColor: c.border, marginVertical: spacing.sm },
  totalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingTop: spacing.sm },
  totalLabel: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  totalValue: { fontSize: 32, fontWeight: "800", color: c.onSurface, letterSpacing: -1 },
  methodCard: { backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, borderWidth: 1, borderColor: c.border },
  methodRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  methodTitle: { color: c.onSurface, fontWeight: "700", fontSize: 15 },
  methodSub: { color: c.muted, fontSize: 12 },
  primary: { backgroundColor: c.brand, borderRadius: radius.pill, paddingVertical: 20, alignItems: "center", ...shadow.card },
  primaryText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 17 },
  processing: { alignItems: "center", gap: spacing.md, padding: spacing.xl },
  processingText: { color: c.muted, fontSize: 14 },
  error: { color: c.error, fontSize: 14, textAlign: "center" },
});
