import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, FlatList, ScrollView, TextInput, ActivityIndicator, Platform } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as ble from "@/src/lib/ble";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

export default function DevBleScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const [status, setStatus] = useState<string>("Idle");
  const [scanning, setScanning] = useState(false);
  const [devices, setDevices] = useState<Record<string, ble.Advertisement>>({});
  const [selected, setSelected] = useState<any>(null);
  const [services, setServices] = useState<ble.BleService[]>([]);
  const [connecting, setConnecting] = useState(false);
  const [notifyLog, setNotifyLog] = useState<{ time: string; hex: string; char: string }[]>([]);
  const [writeChar, setWriteChar] = useState<{ svc: string; ch: string } | null>(null);
  const [writeHex, setWriteHex] = useState("");
  const stopScanRef = useRef<() => void>(() => {});

  useEffect(() => () => { stopScanRef.current?.(); }, []);

  const startScan = async () => {
    setDevices({});
    setStatus("Checking BLE…");
    const r = await ble.ensureReady();
    if (!r.ok) { setStatus(r.reason || "BLE not ready"); return; }
    setStatus("Scanning…");
    setScanning(true);
    Haptics.selectionAsync();
    stopScanRef.current = ble.startScan((d) => {
      setDevices((prev) => ({ ...prev, [d.id]: d }));
    });
    setTimeout(() => {
      stopScanRef.current?.();
      setScanning(false);
      setStatus(`Scan done`);
    }, 15000);
  };

  const stopScan = () => { stopScanRef.current?.(); setScanning(false); setStatus("Scan stopped"); };

  const connectTo = async (id: string, name: string | null) => {
    stopScanRef.current?.(); setScanning(false);
    setConnecting(true); setSelected(null); setServices([]); setNotifyLog([]);
    setStatus(`Connecting to ${name || id}…`);
    try {
      const dev = await ble.connect(id);
      const svcs = await ble.listServices(dev);
      setSelected(dev); setServices(svcs);
      setStatus(`Connected — ${svcs.length} services`);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (e: any) {
      setStatus(`Connect failed: ${e.message || e}`);
    } finally { setConnecting(false); }
  };

  const disconnect = async () => {
    if (!selected) return;
    await ble.disconnect(selected); setSelected(null); setServices([]); setNotifyLog([]);
    setStatus("Disconnected");
  };

  const subscribe = async (svc: string, ch: string) => {
    if (!selected) return;
    try {
      ble.subscribeHex(selected, svc, ch, (hex) => {
        setNotifyLog((prev) => [{ time: new Date().toLocaleTimeString(), hex, char: ch.slice(0, 8) }, ...prev.slice(0, 40)]);
      });
      setStatus(`Subscribed to ${ch.slice(0, 8)}…`);
    } catch (e: any) { setStatus(`Subscribe failed: ${e.message || e}`); }
  };

  const write = async () => {
    if (!selected || !writeChar || !writeHex) return;
    try {
      await ble.writeHex(selected, writeChar.svc, writeChar.ch, writeHex.replace(/\s+/g, ""));
      setStatus(`Wrote ${writeHex.length / 2} bytes to ${writeChar.ch.slice(0, 8)}…`);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } catch (e: any) { setStatus(`Write failed: ${e.message || e}`); }
  };

  const list = Object.values(devices).sort((a, b) => (b.rssi ?? -999) - (a.rssi ?? -999));

  return (
    <View style={[styles.container, { paddingTop: insets.top + spacing.md, paddingBottom: insets.bottom + spacing.lg }]} testID="dev-ble-screen">
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="dev-ble-close">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Developer · BLE</Text>
        <View style={{ width: 40 }} />
      </View>

      {!ble.HAS_BLE && (
        <View style={styles.warn} testID="dev-ble-warn">
          <Ionicons name="warning" size={18} color={colors.warning} />
          <Text style={styles.warnText}>
            BLE isn't available here. This screen only works in a dev build on iOS / Android — click Publish → Generate build.
          </Text>
        </View>
      )}

      <View style={styles.status}>
        <Ionicons name="pulse-outline" size={16} color={colors.muted} />
        <Text style={styles.statusText} numberOfLines={2}>{status}</Text>
      </View>

      <View style={styles.actionsRow}>
        <Pressable testID="dev-ble-scan" onPress={scanning ? stopScan : startScan} style={[styles.primary, { flex: 1 }]}>
          {scanning ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Ionicons name="scan" size={18} color={colors.onBrandPrimary} />}
          <Text style={styles.primaryText}>{scanning ? "Stop scan" : "Scan for scooters"}</Text>
        </Pressable>
        {selected && (
          <Pressable testID="dev-ble-disconnect" onPress={disconnect} style={styles.secondary}>
            <Ionicons name="close-circle" size={18} color={colors.onSurface} />
            <Text style={styles.secondaryText}>Disconnect</Text>
          </Pressable>
        )}
      </View>

      {!selected ? (
        <FlatList
          data={list}
          keyExtractor={(d) => d.id}
          ItemSeparatorComponent={() => <View style={{ height: 6 }} />}
          contentContainerStyle={{ paddingBottom: 40 }}
          renderItem={({ item }) => (
            <Pressable testID={`dev-ble-device-${item.id}`} onPress={() => connectTo(item.id, item.name)} style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowName}>{item.name || "(no name)"}</Text>
                <Text style={styles.rowMeta}>{item.id} · RSSI {item.rssi ?? "?"}</Text>
                {item.serviceUUIDs && item.serviceUUIDs.length > 0 && (
                  <Text style={styles.rowMeta} numberOfLines={1}>svc {item.serviceUUIDs.join(", ").slice(0, 60)}</Text>
                )}
              </View>
              {connecting ? <ActivityIndicator color={colors.brand} /> : <Ionicons name="chevron-forward" size={18} color={colors.muted} />}
            </Pressable>
          )}
          ListEmptyComponent={<Text style={{ color: colors.muted, textAlign: "center", padding: spacing.xl }}>No devices yet. Tap scan.</Text>}
        />
      ) : (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 40 }}>
          {services.map((s) => (
            <View key={s.uuid} style={styles.svc}>
              <Text style={styles.svcTitle}>service {s.uuid}</Text>
              {s.characteristics.map((c) => (
                <View key={c.uuid} style={styles.char}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.charUUID}>{c.uuid}</Text>
                    <Text style={styles.charProps}>
                      {[c.isReadable && "R", c.isWritable && "W", c.isNotifiable && "N"].filter(Boolean).join("·")}
                    </Text>
                  </View>
                  {c.isNotifiable && (
                    <Pressable onPress={() => subscribe(s.uuid, c.uuid)} style={styles.mini}>
                      <Text style={styles.miniText}>Notify</Text>
                    </Pressable>
                  )}
                  {c.isWritable && (
                    <Pressable onPress={() => setWriteChar({ svc: s.uuid, ch: c.uuid })} style={[styles.mini, writeChar?.ch === c.uuid && { backgroundColor: colors.brand }]}>
                      <Text style={[styles.miniText, writeChar?.ch === c.uuid && { color: colors.onBrandPrimary }]}>Write</Text>
                    </Pressable>
                  )}
                </View>
              ))}
            </View>
          ))}

          {writeChar && (
            <View style={styles.writeBox}>
              <Text style={styles.writeTitle}>Write hex bytes to {writeChar.ch.slice(0, 8)}…</Text>
              <TextInput
                testID="dev-ble-write-hex"
                value={writeHex}
                onChangeText={setWriteHex}
                placeholder="e.g. 5501030002"
                placeholderTextColor={colors.muted}
                style={styles.writeInput}
                autoCapitalize="none"
              />
              <Pressable testID="dev-ble-write-send" onPress={write} style={styles.primary}>
                <Ionicons name="send" size={16} color={colors.onBrandPrimary} />
                <Text style={styles.primaryText}>Send</Text>
              </Pressable>
            </View>
          )}

          {notifyLog.length > 0 && (
            <View style={styles.logBox}>
              <Text style={styles.writeTitle}>Notify log</Text>
              {notifyLog.map((l, i) => (
                <Text key={i} style={styles.logLine}>[{l.time}] {l.char}… {l.hex}</Text>
              ))}
            </View>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  container: { flex: 1, backgroundColor: c.surface, paddingHorizontal: spacing.lg, gap: spacing.md },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: c.border },
  title: { fontSize: 20, fontWeight: "800", color: c.onSurface },
  warn: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: "#FFF7E0", padding: spacing.md, borderRadius: radius.md },
  warnText: { flex: 1, color: "#7A5A00", fontSize: 12, lineHeight: 16 },
  status: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: c.surfaceTertiary, padding: spacing.md, borderRadius: radius.md },
  statusText: { color: c.onSurface, fontSize: 12, flex: 1 },
  actionsRow: { flexDirection: "row", gap: spacing.sm },
  primary: { flexDirection: "row", gap: spacing.sm, alignItems: "center", justifyContent: "center", backgroundColor: c.brand, borderRadius: radius.pill, paddingVertical: 14, paddingHorizontal: spacing.lg, ...shadow.card },
  primaryText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 14 },
  secondary: { flexDirection: "row", gap: spacing.xs, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceSecondary, borderRadius: radius.pill, paddingVertical: 14, paddingHorizontal: spacing.lg, borderWidth: 1, borderColor: c.border },
  secondaryText: { color: c.onSurface, fontWeight: "700", fontSize: 14 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: c.surfaceSecondary, padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: c.border },
  rowName: { color: c.onSurface, fontWeight: "700", fontSize: 14 },
  rowMeta: { color: c.muted, fontSize: 11, marginTop: 2, fontVariant: ["tabular-nums"] as any },
  svc: { backgroundColor: c.surfaceSecondary, padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.sm, borderWidth: 1, borderColor: c.border },
  svcTitle: { color: c.muted, fontSize: 10, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", marginBottom: spacing.xs },
  char: { flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.border },
  charUUID: { color: c.onSurface, fontSize: 11, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" },
  charProps: { color: c.muted, fontSize: 10, marginTop: 2 },
  mini: { backgroundColor: c.surfaceTertiary, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8 },
  miniText: { color: c.onSurface, fontSize: 11, fontWeight: "700" },
  writeBox: { backgroundColor: c.surfaceSecondary, padding: spacing.md, borderRadius: radius.md, marginTop: spacing.md, gap: spacing.sm, borderWidth: 1, borderColor: c.border },
  writeTitle: { color: c.onSurface, fontWeight: "700", fontSize: 13 },
  writeInput: { backgroundColor: c.surfaceTertiary, color: c.onSurface, padding: spacing.sm, borderRadius: radius.sm, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", fontSize: 13 },
  logBox: { backgroundColor: c.surfaceInverse, padding: spacing.md, borderRadius: radius.md, marginTop: spacing.md, gap: 4 },
  logLine: { color: c.onSurfaceInverse, fontSize: 10, fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" },
});
