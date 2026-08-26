import { useEffect, useState, useCallback, useMemo } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, Ride } from "@/src/lib/api";
import { spacing, radius } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

export default function History() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  const [rides, setRides] = useState<Ride[]>([]);
  const [loading, setLoading] = useState(true);
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const load = useCallback(async () => {
    try { const r = await api.listRides(); setRides(r); } catch {} finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <View style={[styles.container, { paddingTop: insets.top + spacing.md }]} testID="history-screen">
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="history-close">
          <Ionicons name="close" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Your rides</Text>
        <View style={{ width: 40 }} />
      </View>
      {loading ? (
        <ActivityIndicator color={colors.brand} size="large" style={{ marginTop: 40 }} />
      ) : rides.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="bicycle-outline" size={40} color={colors.muted} />
          <Text style={styles.emptyText}>No rides yet</Text>
          <Text style={styles.emptySub}>Scan a scooter to take your first ride</Text>
        </View>
      ) : (
        <FlatList
          data={rides}
          keyExtractor={(r) => r.ride_id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: insets.bottom + spacing.lg }}
          ItemSeparatorComponent={() => <View style={{ height: spacing.sm }} />}
          renderItem={({ item }) => <RideCard ride={item} styles={styles} colors={colors} />}
        />
      )}
    </View>
  );
}

function RideCard({ ride, styles, colors }: any) {
  const date = new Date(ride.created_at);
  const dateStr = date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const timeStr = date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const dollars = (ride.amount_cents / 100).toFixed(2);
  const statusColor = ride.status === "paid" ? colors.brandSecondary : ride.status === "awaiting_payment" ? colors.warning : colors.muted;
  return (
    <View style={styles.card} testID={`ride-card-${ride.ride_id}`}>
      <View style={styles.iconBox}><Ionicons name="flash" size={20} color={colors.onBrandPrimary} /></View>
      <View style={{ flex: 1 }}>
        <Text style={styles.cardTitle}>{ride.scooter_code}</Text>
        <Text style={styles.cardSub}>{dateStr} · {timeStr} · {ride.minutes} min · {(ride.distance_m/1609).toFixed(1)} mi</Text>
      </View>
      <View style={{ alignItems: "flex-end" }}>
        <Text style={styles.price}>${dollars}</Text>
        <Text style={[styles.status, { color: statusColor }]}>{ride.status.replace("_", " ")}</Text>
      </View>
    </View>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  container: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, marginBottom: spacing.md },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: c.border },
  title: { fontSize: 20, fontWeight: "800", color: c.onSurface },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  emptyText: { fontSize: 18, fontWeight: "700", color: c.onSurface, marginTop: spacing.md },
  emptySub: { color: c.muted, fontSize: 13 },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: c.surfaceSecondary, padding: spacing.lg, borderRadius: radius.md, borderWidth: 1, borderColor: c.border },
  iconBox: { width: 42, height: 42, borderRadius: 21, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
  cardTitle: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  cardSub: { color: c.muted, fontSize: 12, marginTop: 2 },
  price: { fontSize: 18, fontWeight: "800", color: c.onSurface },
  status: { fontSize: 11, fontWeight: "700", textTransform: "uppercase", marginTop: 2 },
});
