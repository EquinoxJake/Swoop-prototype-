import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Platform, TextInput } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import * as Location from "expo-location";
import { BlurView } from "expo-blur";
import BottomSheet, { BottomSheetView, BottomSheetFlatList } from "@gorhom/bottom-sheet";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import NativeMap, { IS_NATIVE_MAP } from "@/src/components/NativeMap";
import { api, Scooter, Ride } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import { spacing, radius, shadow, batteryColor } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

function distanceMi(a: { lat: number; lng: number } | null, b: { lat: number; lng: number }) {
  if (!a) return null;
  const R = 3958.8;
  const p1 = (a.lat * Math.PI) / 180;
  const p2 = (b.lat * Math.PI) / 180;
  const dp = ((b.lat - a.lat) * Math.PI) / 180;
  const dl = ((b.lng - a.lng) * Math.PI) / 180;
  const c = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(c));
}

export default function MapScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const { colors, isDark } = useTheme();
  const [scooters, setScooters] = useState<Scooter[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Scooter | null>(null);
  const [activeRide, setActiveRide] = useState<Ride | null>(null);
  const [userLoc, setUserLoc] = useState<{ lat: number; lng: number } | null>(null);
  const [query, setQuery] = useState("");
  const mapRef = useRef<any>(null);
  const sheetRef = useRef<BottomSheet>(null);
  const snapPoints = useMemo(() => ["14%", "55%", "92%"], []);
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const loadData = useCallback(async () => {
    try {
      const [s, ride] = await Promise.all([api.listScooters(), api.getActiveRide().catch(() => null)]);
      setScooters(s); setActiveRide(ride);
    } catch (e) { console.warn(e); } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { loadData(); }, [loadData]));

  useEffect(() => {
    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status === "granted") {
          const pos = await Location.getCurrentPositionAsync({});
          const loc = { lat: pos.coords.latitude, lng: pos.coords.longitude };
          setUserLoc(loc);
          try {
            const near = await api.seedNear(loc.lat, loc.lng, 500, 12);
            if (near.length > 0) {
              setScooters((prev) => {
                const map = new Map(prev.map((p) => [p.scooter_id, p]));
                near.forEach((n) => map.set(n.scooter_id, n));
                return Array.from(map.values());
              });
              mapRef.current?.animateToRegion?.({ latitude: loc.lat, longitude: loc.lng, latitudeDelta: 0.008, longitudeDelta: 0.008 }, 600);
            }
          } catch (e) { console.warn("seedNear failed", e); }
        }
      } catch {}
    })();
  }, []);

  useEffect(() => {
    if (activeRide) {
      if (activeRide.status === "awaiting_payment") router.replace(`/(app)/receipt?ride_id=${activeRide.ride_id}`);
      else router.replace(`/(app)/ride?ride_id=${activeRide.ride_id}`);
    }
  }, [activeRide, router]);

  const onPinPress = (s: Scooter) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSelected(s);
    sheetRef.current?.snapToIndex(1);
    mapRef.current?.animateToRegion?.({ latitude: s.lat, longitude: s.lng, latitudeDelta: 0.006, longitudeDelta: 0.006 }, 400);
  };
  const onListSelect = (s: Scooter) => {
    Haptics.selectionAsync(); setSelected(s);
    mapRef.current?.animateToRegion?.({ latitude: s.lat, longitude: s.lng, latitudeDelta: 0.006, longitudeDelta: 0.006 }, 400);
  };
  const onUnlock = async () => {
    if (!selected) return;
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    try { const ride = await api.reserveRide(selected.code); router.push(`/(app)/ride?ride_id=${ride.ride_id}`); }
    catch (e: any) { alert(e.message || "Could not reserve"); }
  };
  const centerOnUser = () => {
    if (userLoc && mapRef.current) mapRef.current.animateToRegion?.({ latitude: userLoc.lat, longitude: userLoc.lng, latitudeDelta: 0.01, longitudeDelta: 0.01 }, 500);
  };

  const sortedScooters = useMemo(() => {
    const q = query.trim().toUpperCase();
    const filtered = q ? scooters.filter((s) => s.code.toUpperCase().includes(q)) : scooters;
    return [...filtered].sort((a, b) => {
      const da = distanceMi(userLoc, a); const db = distanceMi(userLoc, b);
      if (da !== null && db !== null) return da - db;
      return a.code.localeCompare(b.code);
    });
  }, [scooters, userLoc, query]);

  const availableCount = scooters.filter((s) => s.status === "available").length;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <View style={styles.container} testID="map-screen">
        <NativeMap scooters={scooters} onPinPress={onPinPress} mapRef={mapRef} />
        {loading && !IS_NATIVE_MAP && (
          <ActivityIndicator style={{ position: "absolute", top: 200, alignSelf: "center" }} color={colors.brand} />
        )}

        <View style={[styles.topBar, { top: insets.top + spacing.md }]} pointerEvents="box-none">
          <GlassPill testID="profile-pill" onPress={() => router.push("/(app)/profile")} colors={colors} styles={styles}>
            <Ionicons name="person-circle-outline" size={22} color={colors.onSurface} />
            <Text style={styles.pillText} numberOfLines={1}>{user?.name || user?.email?.split("@")[0] || "You"}</Text>
          </GlassPill>
          <GlassPill testID="history-pill" onPress={() => router.push("/(app)/history")} colors={colors} styles={styles}>
            <Ionicons name="time-outline" size={20} color={colors.onSurface} />
            <Text style={styles.pillText}>Rides</Text>
          </GlassPill>
        </View>

        <View style={[styles.countPill, { top: insets.top + 72 }]} pointerEvents="none">
          <View style={styles.dot} />
          <Text style={styles.countText}>{loading ? "Finding scooters…" : `${availableCount} scooters nearby`}</Text>
        </View>

        <View style={[styles.fabColumn, { bottom: insets.bottom + 240 }]}>
          <Pressable testID="center-location-fab" onPress={centerOnUser} style={({ pressed }) => [styles.fab, pressed && { opacity: 0.8 }]}>
            <Ionicons name="locate" size={22} color={colors.onSurface} />
          </Pressable>
        </View>

        <View style={[styles.scanBar, { bottom: insets.bottom + 130 }]}>
          <Pressable testID="scan-to-ride-button" onPress={() => { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium); router.push("/(app)/scan"); }} style={({ pressed }) => [styles.scanBtn, pressed && { opacity: 0.9 }]}>
            <Ionicons name="qr-code" size={24} color={colors.onBrandPrimary} />
            <Text style={styles.scanText}>Scan to Ride</Text>
          </Pressable>
        </View>

        <BottomSheet
          ref={sheetRef}
          index={0}
          snapPoints={snapPoints}
          enableDynamicSizing={false}
          backgroundStyle={{ backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg }}
          handleIndicatorStyle={{ backgroundColor: colors.borderStrong, width: 48, height: 5 }}
        >
          {selected ? (
            <BottomSheetView>
              <ScooterDetail scooter={selected} userLoc={userLoc} onUnlock={onUnlock} onBack={() => setSelected(null)} colors={colors} styles={styles} />
            </BottomSheetView>
          ) : (
            <ListArea query={query} onQuery={setQuery} count={sortedScooters.length} userLoc={userLoc} scooters={sortedScooters} onSelect={onListSelect} insetsBottom={insets.bottom} colors={colors} styles={styles} />
          )}
        </BottomSheet>
      </View>
    </GestureHandlerRootView>
  );
}

function ListArea({ query, onQuery, count, userLoc, scooters, onSelect, insetsBottom, colors, styles }: any) {
  return (
    <BottomSheetFlatList
      data={scooters}
      keyExtractor={(s: Scooter) => s.scooter_id}
      contentContainerStyle={{ paddingBottom: insetsBottom + spacing.xl, paddingHorizontal: spacing.lg }}
      ListHeaderComponent={
        <View style={{ paddingBottom: spacing.md }}>
          <View style={styles.listHeaderRow}>
            <Text style={styles.listTitle}>Nearby scooters</Text>
            <Text style={styles.listCount}>{count}</Text>
          </View>
          <View style={styles.searchWrap}>
            <Ionicons name="search" size={16} color={colors.muted} />
            <TextInput testID="scooter-search-input" value={query} onChangeText={onQuery} placeholder="Search by code (e.g. SW-1000)" placeholderTextColor={colors.muted} style={styles.searchInput} autoCapitalize="characters" />
          </View>
        </View>
      }
      renderItem={({ item }: any) => <ListItem scooter={item} userLoc={userLoc} onPress={() => onSelect(item)} colors={colors} styles={styles} />}
      ItemSeparatorComponent={() => <View style={{ height: spacing.sm }} />}
      ListEmptyComponent={
        <View style={{ padding: spacing.xl, alignItems: "center" }}>
          <Ionicons name="bicycle-outline" size={30} color={colors.muted} />
          <Text style={{ color: colors.muted, marginTop: spacing.sm }}>No scooters found</Text>
        </View>
      }
    />
  );
}

function ListItem({ scooter, userLoc, onPress, colors, styles }: any) {
  const dist = distanceMi(userLoc, scooter);
  const distStr = dist === null ? "—" : dist < 0.1 ? `${Math.round(dist * 5280)} ft` : `${dist.toFixed(1)} mi`;
  return (
    <Pressable testID={`list-scooter-${scooter.code}`} onPress={onPress} style={({ pressed }) => [styles.listItem, pressed && { opacity: 0.85 }]}>
      <View style={[styles.listIcon, { backgroundColor: batteryColor(scooter.battery, colors) }]}>
        <Ionicons name="flash" size={16} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.listCode}>{scooter.code}</Text>
        <Text style={styles.listSub}>{scooter.battery}% · {distStr}{scooter.status !== "available" ? ` · ${scooter.status}` : ""}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  );
}

function ScooterDetail({ scooter, userLoc, onUnlock, onBack, colors, styles }: any) {
  const price = `$${(scooter.unlock_fee_cents / 100).toFixed(2)} + $${(scooter.price_per_min_cents / 100).toFixed(2)}/min`;
  const dist = distanceMi(userLoc, scooter);
  const distStr = dist === null ? "" : dist < 0.1 ? `${Math.round(dist * 5280)} ft away` : `${dist.toFixed(1)} mi away`;
  return (
    <View style={styles.sheetContent} testID="scooter-detail-sheet">
      <View style={styles.sheetHeader}>
        <Pressable testID="detail-back" onPress={onBack} style={styles.smallBack}>
          <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.sheetCode} testID="scooter-code">{scooter.code}</Text>
          <Text style={styles.sheetModel}>{scooter.model} · {distStr}</Text>
        </View>
        <View style={[styles.batteryPill, { backgroundColor: batteryColor(scooter.battery, colors) }]}>
          <Ionicons name="battery-charging" size={16} color="#fff" />
          <Text style={styles.batteryText}>{scooter.battery}%</Text>
        </View>
      </View>
      <View style={styles.metricsRow}>
        <Metric icon="speedometer-outline" label="Top speed" value="15 mph" colors={colors} styles={styles} />
        <Metric icon="map-outline" label="Range" value={`~${Math.round(scooter.battery * 0.25)} mi`} colors={colors} styles={styles} />
        <Metric icon="pricetag-outline" label="Price" value={price} tight colors={colors} styles={styles} />
      </View>
      <View style={styles.perksRow}>
        <Perk icon="shield-checkmark" text="Insurance included" colors={colors} styles={styles} />
        <Perk icon="flash" text="Instant unlock via BLE" colors={colors} styles={styles} />
      </View>
      <Pressable testID="unlock-scooter-button" onPress={onUnlock} style={({ pressed }) => [styles.unlockBtn, pressed && { opacity: 0.9 }]}>
        <Ionicons name="lock-open" size={22} color={colors.onBrandPrimary} />
        <Text style={styles.unlockText}>Unlock scooter</Text>
      </Pressable>
    </View>
  );
}

function GlassPill({ children, onPress, testID, colors, styles }: any) {
  return (
    <Pressable testID={testID} onPress={onPress} style={({ pressed }) => [styles.glassPill, pressed && { opacity: 0.85 }]}>
      {Platform.OS !== "web" ? <BlurView intensity={70} tint={colors.onSurface === "#F5F7FA" ? "dark" : "light"} style={StyleSheet.absoluteFill} /> : null}
      <View style={styles.glassPillInner}>{children}</View>
    </Pressable>
  );
}
function Metric({ icon, label, value, tight, colors, styles }: any) {
  return (
    <View style={[styles.metric, tight && { flex: 1.4 }]}>
      <Ionicons name={icon} size={18} color={colors.muted} />
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}
function Perk({ icon, text, colors, styles }: any) {
  return (
    <View style={styles.perk}>
      <Ionicons name={icon} size={16} color={colors.brandSecondary} />
      <Text style={styles.perkText}>{text}</Text>
    </View>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  container: { flex: 1, backgroundColor: c.surface },
  topBar: { position: "absolute", left: spacing.lg, right: spacing.lg, flexDirection: "row", justifyContent: "space-between", gap: spacing.sm },
  glassPill: { borderRadius: radius.pill, overflow: "hidden", backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border, ...shadow.card },
  glassPillInner: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 10 },
  pillText: { color: c.onSurface, fontWeight: "600", fontSize: 13, maxWidth: 100 },
  countPill: { position: "absolute", alignSelf: "center", flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surfaceInverse, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, ...shadow.card },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: c.brandSecondary },
  countText: { color: c.onSurfaceInverse, fontSize: 12, fontWeight: "700" },
  fabColumn: { position: "absolute", right: spacing.lg, gap: spacing.md },
  fab: { width: 52, height: 52, borderRadius: 26, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", ...shadow.floating },
  scanBar: { position: "absolute", left: spacing.lg, right: spacing.lg, alignItems: "center" },
  scanBtn: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: c.brand, paddingHorizontal: 28, paddingVertical: 16, borderRadius: radius.pill, ...shadow.floating },
  scanText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 17 },
  listHeaderRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingTop: spacing.sm },
  listTitle: { fontSize: 20, fontWeight: "800", color: c.onSurface, letterSpacing: -0.5 },
  listCount: { backgroundColor: c.brandTertiary, color: c.onBrandTertiary, fontWeight: "800", paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill, fontSize: 12, overflow: "hidden" },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10, marginTop: spacing.md },
  searchInput: { flex: 1, fontSize: 14, color: c.onSurface, letterSpacing: 0.5 },
  listItem: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.md },
  listIcon: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  listCode: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  listSub: { fontSize: 12, color: c.muted, marginTop: 2 },
  sheetContent: { padding: spacing.xl, gap: spacing.lg },
  sheetHeader: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  smallBack: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  sheetCode: { fontSize: 24, fontWeight: "800", color: c.onSurface, letterSpacing: -0.5 },
  sheetModel: { color: c.muted, marginTop: 2, fontSize: 13 },
  batteryPill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill },
  batteryText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  metricsRow: { flexDirection: "row", gap: spacing.sm },
  metric: { flex: 1, backgroundColor: c.surfaceTertiary, padding: spacing.md, borderRadius: radius.md, gap: 4 },
  metricLabel: { color: c.muted, fontSize: 11 },
  metricValue: { color: c.onSurface, fontWeight: "700", fontSize: 14 },
  perksRow: { flexDirection: "row", gap: spacing.md, flexWrap: "wrap" },
  perk: { flexDirection: "row", alignItems: "center", gap: 6 },
  perkText: { color: c.onSurface, fontSize: 13 },
  unlockBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: c.brand, borderRadius: radius.pill, paddingVertical: 18, ...shadow.card },
  unlockText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 17 },
});
