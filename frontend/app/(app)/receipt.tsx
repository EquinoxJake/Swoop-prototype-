import { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, Ride, PaymentMethod } from "@/src/lib/api";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";
import RouteMap from "@/src/components/RouteMap";

export default function Receipt() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { colors } = useTheme();
  const { ride_id } = useLocalSearchParams<{ ride_id: string }>();
  const [ride, setRide] = useState<Ride | null>(null);
  const [card, setCard] = useState<PaymentMethod | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const styles = useMemo(() => makeStyles(colors), [colors]);

  useEffect(() => {
    if (!ride_id) return;
    (async () => {
      try {
        const r = await api.getRide(ride_id);
        setRide(r);
        if (r.payment_method_id) {
          const pms = await api.listPaymentMethods();
          const c = pms.find((p) => p.payment_method_id === r.payment_method_id);
          if (c) setCard(c);
        }
      } catch (e: any) { setErr(e.message); }
    })();
  }, [ride_id]);

  if (!ride) return <View style={styles.loading}><ActivityIndicator color={colors.brand} size="large" /></View>;

  const total = (ride.amount_cents / 100).toFixed(2);
  const unlock = (ride.unlock_charged_cents / 100).toFixed(2);
  const mileage = (ride.mileage_charged_cents / 100).toFixed(2);
  const miles = ride.miles.toFixed(2);

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }} testID="receipt-screen">
      <ScrollView contentContainerStyle={[styles.container, { paddingTop: insets.top + spacing.xxl, paddingBottom: insets.bottom + spacing.xxl }]}>
        <View style={styles.header}>
          <View style={[styles.badge, { backgroundColor: colors.brandSecondary }]}>
            <Ionicons name="checkmark" size={28} color={colors.onBrandSecondary} />
          </View>
          <Text style={styles.title}>Ride complete!</Text>
          <Text style={styles.sub}>Thanks for riding Swoop</Text>
        </View>

        {ride.route && ride.route.length >= 2 && (
          <View style={{ gap: spacing.xs }}>
            <Text style={styles.routeLabel}>Your route</Text>
            <RouteMap route={ride.route} height={200} />
          </View>
        )}

        <View style={styles.card}>
          <Row label="Duration" value={`${ride.minutes} min`} styles={styles} />
          <Row label="Distance (GPS)" value={`${miles} mi`} styles={styles} />
          {(ride.paused_seconds ?? 0) > 0 && (
            <Row
              label="Paused (not billed)"
              value={formatDuration(ride.paused_seconds || 0)}
              styles={styles}
              colors={colors}
              muted
            />
          )}
          <Row label="Scooter" value={ride.scooter_code} styles={styles} />
          <View style={styles.hr} />
          <Row label="Unlock fee" value={`$${unlock}`} muted styles={styles} colors={colors} />
          <Row label={`Mileage (${miles} mi × $0.20)`} value={`$${mileage}`} muted styles={styles} colors={colors} />
          <View style={styles.hr} />
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Total charged</Text>
            <Text style={styles.totalValue} testID="receipt-total">${total}</Text>
          </View>
        </View>

        <View style={styles.methodCard}>
          <View style={styles.methodRow}>
            <Ionicons name="card-outline" size={22} color={colors.onSurface} />
            <View style={{ flex: 1 }}>
              <Text style={styles.methodTitle}>{card ? `${card.brand} •••• ${card.last4}` : "Card on file"}</Text>
              <Text style={styles.methodSub}>Auto-charged (MOCKED · no real charge)</Text>
            </View>
            <Ionicons name="checkmark-circle" size={22} color={colors.brandSecondary} />
          </View>
        </View>

        {err && <Text style={styles.error} testID="receipt-error">{err}</Text>}

        <Pressable testID="done-button" onPress={() => router.replace("/(app)/map")} style={({ pressed }) => [styles.primary, pressed && { opacity: 0.9 }]}>
          <Text style={styles.primaryText}>Done</Text>
        </Pressable>
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

function formatDuration(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

const makeStyles = (c: any) => StyleSheet.create({
  loading: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.surface },
  container: { padding: spacing.xl, gap: spacing.lg },
  routeLabel: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase", letterSpacing: 0.5, marginLeft: spacing.xs },
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
  error: { color: c.error, fontSize: 14, textAlign: "center" },
});
