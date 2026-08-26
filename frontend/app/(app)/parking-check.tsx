import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView, Platform, Image } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import * as Location from "expo-location";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { CameraView, useCameraPermissions, HAS_CAMERA } from "@/src/components/Camera";
import { api, ParkingCheck } from "@/src/lib/api";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

type Phase = "checking" | "rules" | "camera" | "review" | "uploading" | "done" | "error";

export default function ParkingCheckScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { colors } = useTheme();
  const {
    ride_id,
    distance_m,
    paused_seconds,
    route_json,
    end_lat,
    end_lng,
  } = useLocalSearchParams<{
    ride_id: string;
    distance_m?: string;
    paused_seconds?: string;
    route_json?: string;
    end_lat?: string;
    end_lng?: string;
  }>();

  const [phase, setPhase] = useState<Phase>("checking");
  const [check, setCheck] = useState<ParkingCheck | null>(null);
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [override, setOverride] = useState(false);
  const [permission, requestPermission] = useCameraPermissions();
  const camRef = useRef<any>(null);
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const parsedRoute: number[][] = useMemo(() => {
    try { return route_json ? JSON.parse(String(route_json)) : []; } catch { return []; }
  }, [route_json]);
  const distNum = Number(distance_m ?? "0");
  const pausedNum = Number(paused_seconds ?? "0");

  // Step 1: check GPS zone
  useEffect(() => {
    (async () => {
      try {
        let lat = end_lat ? Number(end_lat) : NaN;
        let lng = end_lng ? Number(end_lng) : NaN;
        if (Number.isNaN(lat) || Number.isNaN(lng)) {
          const { status } = await Location.requestForegroundPermissionsAsync();
          if (status === "granted") {
            const pos = await Location.getCurrentPositionAsync({});
            lat = pos.coords.latitude; lng = pos.coords.longitude;
          }
        }
        if (!Number.isNaN(lat) && !Number.isNaN(lng)) {
          const res = await api.parkingCheck(lat, lng);
          setCheck({ ...res, __lat: lat, __lng: lng } as any);
        } else {
          setCheck({ ok: true, reason: "GPS unavailable — please park responsibly" } as any);
        }
      } catch (e: any) {
        setCheck({ ok: true, reason: "Zone check unavailable" } as any);
      } finally {
        setPhase("rules");
      }
    })();
  }, [end_lat, end_lng]);

  const takePhoto = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    if (!HAS_CAMERA) {
      setErr("Camera isn't available on web preview. Open the app in Expo Go on your phone.");
      return;
    }
    if (permission && !permission.granted) {
      const r = await requestPermission();
      if (!r?.granted) { setErr("Camera permission is required to end the ride"); return; }
    }
    setPhase("camera");
  };

  const capture = async () => {
    if (!camRef.current) return;
    try {
      const shot = await camRef.current.takePictureAsync({ quality: 0.7, skipProcessing: true });
      if (!shot?.uri) throw new Error("No image captured");
      setPhotoUri(shot.uri);
      setPhase("review");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (e: any) {
      setErr(e.message || "Could not capture photo");
      setPhase("rules");
    }
  };

  const retake = () => { setPhotoUri(null); setPhase("camera"); };

  const submit = async () => {
    if (!photoUri || !ride_id) return;
    setErr(null); setPhase("uploading");
    try {
      // 1) Upload photo to Object Storage via backend
      const up = await api.uploadParkingPhoto(String(ride_id), photoUri, "image/jpeg");
      // 2) Complete ride
      const endLat = end_lat ? Number(end_lat) : undefined;
      const endLng = end_lng ? Number(end_lng) : undefined;
      const updated = await api.endRide(
        String(ride_id),
        Math.round(distNum),
        endLat,
        endLng,
        parsedRoute,
        pausedNum,
        up.path,
        override,
      );
      router.replace(`/(app)/receipt?ride_id=${updated.ride_id}`);
    } catch (e: any) {
      if (e?.status === 409 && String(e.message).toLowerCase().includes("bad_parking")) {
        setErr("This spot isn't allowed. Move to a bike rack or the edge of a sidewalk and try again.");
      } else {
        setErr(e.message || "Failed to finish ride");
      }
      setPhase("review");
    }
  };

  // ---- Render ----
  if (phase === "checking") {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.brand} />
        <Text style={styles.checkingText}>Checking parking area…</Text>
      </View>
    );
  }

  if (phase === "camera") {
    return (
      <View style={styles.container} testID="parking-camera">
        {HAS_CAMERA ? (
          <CameraView ref={camRef} style={StyleSheet.absoluteFill} facing="back" />
        ) : (
          <View style={[StyleSheet.absoluteFill, { backgroundColor: "#000" }]} />
        )}
        {/* Guide overlay */}
        <View style={styles.overlay} pointerEvents="none">
          <View style={styles.frame}>
            <Text style={styles.frameLabel}>Frame the scooter</Text>
            <View style={styles.iconRow}>
              <Ionicons name="bicycle" size={40} color={colors.brand} />
            </View>
            <Text style={styles.frameHint}>Show the scooter upright, kickstand down, with the ground around it visible</Text>
          </View>
        </View>
        <Pressable testID="parking-cam-cancel" onPress={() => setPhase("rules")} style={[styles.cancelBtn, { top: insets.top + spacing.md }]}>
          <Ionicons name="close" size={22} color="#fff" />
        </Pressable>
        <View style={[styles.shutterBar, { bottom: insets.bottom + spacing.xl }]}>
          <Pressable testID="parking-cam-shutter" onPress={capture} style={styles.shutterOuter}>
            <View style={styles.shutterInner} />
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + spacing.md, paddingBottom: insets.bottom + spacing.xxl }]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="parking-back">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Park & photo</Text>
        <View style={{ width: 40 }} />
      </View>

      {/* Zone status banner */}
      {check && (
        <View style={[styles.banner, { backgroundColor: check.ok ? colors.brandTertiary : "#FEE4E2" }]} testID="parking-banner">
          <Ionicons name={check.ok ? "checkmark-circle" : "alert-circle"} size={22} color={check.ok ? colors.brandSecondary : colors.error} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.bannerTitle, { color: check.ok ? colors.onBrandTertiary : "#7A1B0F" }]}>
              {check.ok ? "Looks like a valid parking spot" : "No-parking zone"}
            </Text>
            <Text style={[styles.bannerText, { color: check.ok ? colors.onBrandTertiary : "#7A1B0F" }]}>
              {check.reason || (check.ok ? "" : "Move out of the marked area")}
              {check.nearest_allowed && check.nearest_allowed_distance_m !== undefined
                ? `\nNearest rack: ${check.nearest_allowed.name} (${Math.round(check.nearest_allowed_distance_m)}m)`
                : ""}
            </Text>
          </View>
        </View>
      )}

      {/* 3-point checklist */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Before you park</Text>
        <Rule icon="checkmark-circle-outline" title="Kickstand down" desc="Scooter must stand upright on its own" colors={colors} styles={styles} />
        <Rule icon="walk-outline" title="Out of the way" desc="Clear of sidewalks, curb ramps, ADA paths, and doors" colors={colors} styles={styles} />
        <Rule icon="location-outline" title="Approved spot" desc="Bike rack or designated sidewalk parking zone" colors={colors} styles={styles} last />
      </View>

      {/* Photo review */}
      {phase === "review" && photoUri && (
        <View style={styles.card} testID="parking-photo-review">
          <Text style={styles.cardTitle}>Verify photo</Text>
          <Image source={{ uri: photoUri }} style={styles.preview} resizeMode="cover" />
          <View style={styles.reviewRow}>
            <Pressable testID="retake-photo" onPress={retake} style={[styles.secondary]}>
              <Ionicons name="camera-reverse" size={18} color={colors.onSurface} />
              <Text style={styles.secondaryText}>Retake</Text>
            </Pressable>
            <Pressable testID="submit-parking-photo" onPress={submit} style={[styles.primary, { flex: 2 }]}>
              <Ionicons name="checkmark" size={20} color={colors.onBrandPrimary} />
              <Text style={styles.primaryText}>Finish ride</Text>
            </Pressable>
          </View>
        </View>
      )}

      {phase === "uploading" && (
        <View style={styles.processing}>
          <ActivityIndicator size="large" color={colors.brand} />
          <Text style={styles.processingText}>Uploading photo & closing ride…</Text>
        </View>
      )}

      {err && <Text style={styles.error} testID="parking-error">{err}</Text>}

      {phase !== "review" && phase !== "uploading" && (
        <Pressable testID="take-parking-photo" onPress={takePhoto} style={({ pressed }) => [styles.primary, pressed && { opacity: 0.9 }]}>
          <Ionicons name="camera" size={22} color={colors.onBrandPrimary} />
          <Text style={styles.primaryText}>Take parking photo</Text>
        </Pressable>
      )}

      {check && !check.ok && phase !== "uploading" && (
        <Pressable testID="parking-override" onPress={() => setOverride((o) => !o)} style={styles.overrideRow}>
          <Ionicons name={override ? "checkbox" : "square-outline"} size={20} color={colors.muted} />
          <Text style={styles.overrideText}>Park here anyway — I accept a possible $15 improper-parking fee</Text>
        </Pressable>
      )}

      <Text style={styles.footer}>Photos are stored securely with your ride and shown only to you and the Swoop team.</Text>
    </ScrollView>
  );
}

function Rule({ icon, title, desc, colors, styles, last }: any) {
  return (
    <View style={[styles.ruleRow, last && { borderBottomWidth: 0 }]}>
      <Ionicons name={icon} size={22} color={colors.brand} />
      <View style={{ flex: 1 }}>
        <Text style={styles.ruleTitle}>{title}</Text>
        <Text style={styles.ruleDesc}>{desc}</Text>
      </View>
    </View>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  container: { flex: 1, backgroundColor: "#000" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.surface, gap: spacing.md },
  checkingText: { color: c.muted, fontSize: 14 },
  scroll: { padding: spacing.lg, gap: spacing.md, backgroundColor: c.surface, flexGrow: 1 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: c.border },
  title: { fontSize: 20, fontWeight: "800", color: c.onSurface },

  banner: { flexDirection: "row", gap: spacing.sm, padding: spacing.md, borderRadius: radius.md, alignItems: "flex-start" },
  bannerTitle: { fontSize: 14, fontWeight: "800" },
  bannerText: { fontSize: 12, marginTop: 2, lineHeight: 16 },

  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: c.border, ...shadow.card, gap: spacing.xs },
  cardTitle: { fontSize: 15, fontWeight: "800", color: c.onSurface, marginBottom: spacing.sm },
  ruleRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: c.border },
  ruleTitle: { fontSize: 14, fontWeight: "700", color: c.onSurface },
  ruleDesc: { fontSize: 12, color: c.muted, marginTop: 2 },

  preview: { width: "100%", aspectRatio: 3 / 4, borderRadius: radius.md, marginTop: spacing.sm, backgroundColor: c.surfaceTertiary },
  reviewRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },

  primary: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: c.brand, borderRadius: radius.pill, paddingVertical: 18, ...shadow.card },
  primaryText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 16 },
  secondary: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs, backgroundColor: c.surfaceTertiary, borderRadius: radius.pill, paddingVertical: 16 },
  secondaryText: { color: c.onSurface, fontWeight: "700", fontSize: 14 },

  processing: { alignItems: "center", gap: spacing.md, padding: spacing.xl },
  processingText: { color: c.muted, fontSize: 14 },
  error: { color: c.error, fontSize: 13, textAlign: "center" },
  footer: { color: c.muted, fontSize: 11, textAlign: "center", marginTop: spacing.sm, paddingHorizontal: spacing.lg },
  overrideRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  overrideText: { flex: 1, color: c.muted, fontSize: 12, lineHeight: 16 },

  // Camera overlay
  overlay: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  frame: { width: "88%", aspectRatio: 3 / 4, borderRadius: radius.lg, borderWidth: 3, borderColor: c.brand, borderStyle: "dashed", alignItems: "center", justifyContent: "center", padding: spacing.lg, backgroundColor: "rgba(0,0,0,0.15)" },
  frameLabel: { color: "#fff", fontWeight: "800", fontSize: 15, marginBottom: spacing.md },
  iconRow: { marginBottom: spacing.md },
  frameHint: { color: "#fff", fontSize: 12, textAlign: "center", opacity: 0.85 },
  cancelBtn: { position: "absolute", left: spacing.lg, width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: "rgba(255,255,255,0.3)" },
  shutterBar: { position: "absolute", left: 0, right: 0, alignItems: "center" },
  shutterOuter: { width: 78, height: 78, borderRadius: 39, backgroundColor: "rgba(255,255,255,0.25)", alignItems: "center", justifyContent: "center", borderWidth: 4, borderColor: "#fff" },
  shutterInner: { width: 60, height: 60, borderRadius: 30, backgroundColor: "#fff" },
});
