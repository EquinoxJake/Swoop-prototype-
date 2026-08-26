import { useState, useEffect, useMemo } from "react";
import { View, Text, StyleSheet, Pressable, Platform, TextInput } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { CameraView, useCameraPermissions, HAS_CAMERA } from "@/src/components/Camera";
import { api } from "@/src/lib/api";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

export default function Scan() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  const [scanned, setScanned] = useState(false);
  const [flash, setFlash] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [manualCode, setManualCode] = useState("");
  const [permission, requestPermission] = useCameraPermissions();
  const styles = useMemo(() => makeStyles(colors), [colors]);

  useEffect(() => {
    if (HAS_CAMERA && permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  const handleCode = async (raw: string) => {
    if (scanned) return;
    setScanned(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    const m = raw.match(/SW-\d{3,5}/i);
    const code = (m ? m[0] : raw).toUpperCase();
    try {
      const scoot = await api.getScooter(code);
      if (scoot.status !== "available") throw new Error("Scooter not available");
      // Ensure card on file
      const pms = await api.listPaymentMethods();
      if (pms.length === 0) {
        router.replace(`/(app)/payment-method?reserve_after=${encodeURIComponent(code)}`);
        return;
      }
      const ride = await api.reserveRide(code);
      router.replace(`/(app)/ride?ride_id=${ride.ride_id}`);
    } catch (e: any) {
      if (String(e?.message || "").toLowerCase().includes("payment method")) {
        router.replace(`/(app)/payment-method?reserve_after=${encodeURIComponent(code)}`);
        return;
      }
      setErr(e.message || "Invalid QR");
      setTimeout(() => { setErr(null); setScanned(false); }, 1500);
    }
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]} testID="scan-screen">
      {HAS_CAMERA && permission?.granted ? (
        <CameraView
          style={StyleSheet.absoluteFill}
          facing="back"
          enableTorch={flash}
          onBarcodeScanned={scanned ? undefined : ({ data }: any) => handleCode(data)}
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        />
      ) : (
        <View style={[StyleSheet.absoluteFill, { backgroundColor: "#0a0a0a", alignItems: "center", justifyContent: "center", padding: spacing.xl }]}>
          <Ionicons name="camera-outline" size={40} color="#fff" />
          <Text style={styles.permissionText}>
            {!HAS_CAMERA ? "Camera scanning not available on web.\nEnter scooter code below." : "Camera permission needed"}
          </Text>
          {HAS_CAMERA && permission && !permission.granted && (
            <Pressable style={styles.permBtn} onPress={requestPermission}>
              <Text style={styles.permBtnText}>Enable Camera</Text>
            </Pressable>
          )}
        </View>
      )}

      <View style={styles.overlay} pointerEvents="none">
        <View style={styles.cutout}>
          <Corner colors={colors} style={{ top: 0, left: 0 }} />
          <Corner colors={colors} style={{ top: 0, right: 0, transform: [{ rotate: "90deg" }] }} />
          <Corner colors={colors} style={{ bottom: 0, left: 0, transform: [{ rotate: "-90deg" }] }} />
          <Corner colors={colors} style={{ bottom: 0, right: 0, transform: [{ rotate: "180deg" }] }} />
        </View>
        <Text style={styles.hint}>Point at the QR code on the scooter handlebar</Text>
      </View>

      <Pressable testID="scan-close-button" onPress={() => router.back()} style={[styles.closeBtn, { top: insets.top + spacing.md }]}>
        <Ionicons name="close" size={24} color={colors.onSurface} />
      </Pressable>

      {HAS_CAMERA && (
        <Pressable testID="flash-toggle" onPress={() => setFlash(f => !f)} style={[styles.flashBtn, { bottom: insets.bottom + 190 }]}>
          <Ionicons name={flash ? "flashlight" : "flashlight-outline"} size={22} color="#fff" />
        </Pressable>
      )}

      <View style={[styles.manualBox, { bottom: insets.bottom + spacing.lg }]}>
        <Text style={styles.manualLabel}>Or enter scooter code</Text>
        <View style={styles.manualRow}>
          <TextInput testID="scan-manual-input" value={manualCode} onChangeText={setManualCode} placeholder="SW-1000" placeholderTextColor={colors.muted} autoCapitalize="characters" style={styles.manualInput} />
          <Pressable testID="scan-manual-submit" onPress={() => manualCode && handleCode(manualCode)} style={styles.manualBtn}>
            <Text style={styles.manualBtnText}>Go</Text>
          </Pressable>
        </View>
      </View>

      {err && <View style={styles.errBanner} testID="scan-error"><Text style={styles.errText}>{err}</Text></View>}
    </View>
  );
}

function Corner({ style, colors }: any) {
  return <View style={[{ position: "absolute", width: 32, height: 32, borderTopWidth: 4, borderLeftWidth: 4, borderColor: colors.brand, borderTopLeftRadius: 6 }, style]} />;
}

const makeStyles = (c: any) => StyleSheet.create({
  container: { flex: 1, backgroundColor: "#000" },
  overlay: { flex: 1, alignItems: "center", justifyContent: "center" },
  cutout: { width: 260, height: 260, borderRadius: radius.md, marginTop: -50 },
  hint: { color: "#fff", fontSize: 13, marginTop: spacing.xl, paddingHorizontal: spacing.xl, textAlign: "center", opacity: 0.9 },
  closeBtn: { position: "absolute", left: spacing.lg, width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(255,255,255,0.95)", alignItems: "center", justifyContent: "center", ...shadow.card },
  flashBtn: { position: "absolute", alignSelf: "center", width: 48, height: 48, borderRadius: 24, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: "rgba(255,255,255,0.3)" },
  manualBox: { position: "absolute", left: spacing.lg, right: spacing.lg, backgroundColor: c.surfaceSecondary, padding: spacing.lg, borderRadius: radius.lg, ...shadow.floating },
  manualLabel: { color: c.muted, fontSize: 12, marginBottom: spacing.sm, textAlign: "center" },
  manualRow: { flexDirection: "row", gap: spacing.sm },
  manualInput: { flex: 1, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: 12, fontSize: 16, fontWeight: "700", color: c.onSurface, letterSpacing: 1 },
  manualBtn: { backgroundColor: c.brand, paddingHorizontal: spacing.xl, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  manualBtnText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 15 },
  errBanner: { position: "absolute", top: 100, alignSelf: "center", backgroundColor: c.error, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.pill },
  errText: { color: "#fff", fontWeight: "700" },
  permissionText: { color: "#fff", fontSize: 15, textAlign: "center", marginTop: spacing.md, marginBottom: spacing.lg },
  permBtn: { backgroundColor: c.brand, paddingHorizontal: spacing.xl, paddingVertical: 12, borderRadius: radius.pill },
  permBtnText: { color: c.onBrandPrimary, fontWeight: "800" },
});
