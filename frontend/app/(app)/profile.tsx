import { useMemo } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView, Switch } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "@/src/lib/auth";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme, ThemeMode } from "@/src/lib/theme-context";

export default function Profile() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user, signOut } = useAuth();
  const { colors, mode, isDark, setMode, toggle } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const onSignOut = async () => {
    await signOut();
    router.replace("/(auth)/login");
  };

  const onToggle = async () => {
    Haptics.selectionAsync();
    await toggle();
  };

  const chooseMode = async (m: ThemeMode) => {
    Haptics.selectionAsync();
    await setMode(m);
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }} testID="profile-screen">
      <ScrollView contentContainerStyle={[styles.container, { paddingTop: insets.top + spacing.md, paddingBottom: insets.bottom + spacing.xl }]}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="profile-close">
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.title}>Profile</Text>
          <View style={{ width: 40 }} />
        </View>

        <View style={styles.avatarBox}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>
              {(user?.name || user?.email || "?").charAt(0).toUpperCase()}
            </Text>
          </View>
          <Text style={styles.name} testID="profile-name">{user?.name || user?.email?.split("@")[0]}</Text>
          <Text style={styles.email}>{user?.email}</Text>
        </View>

        {/* Appearance settings */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Appearance</Text>
          <View style={styles.rowBtn}>
            <View style={styles.rowIcon}>
              <Ionicons name={isDark ? "moon" : "sunny"} size={20} color={colors.onSurface} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>Dark mode</Text>
              <Text style={styles.rowSub}>{mode === "system" ? "Following system" : isDark ? "On" : "Off"}</Text>
            </View>
            <Switch
              testID="dark-mode-toggle"
              value={isDark}
              onValueChange={onToggle}
              trackColor={{ false: colors.borderStrong, true: colors.brand }}
              thumbColor={"#FFFFFF"}
              ios_backgroundColor={colors.borderStrong}
            />
          </View>
          <View style={styles.segmentRow}>
            <SegBtn label="Light" active={mode === "light"} onPress={() => chooseMode("light")} testID="theme-light" colors={colors} />
            <SegBtn label="Dark" active={mode === "dark"} onPress={() => chooseMode("dark")} testID="theme-dark" colors={colors} />
            <SegBtn label="System" active={mode === "system"} onPress={() => chooseMode("system")} testID="theme-system" colors={colors} />
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Account</Text>
          <SectionRow icon="card-outline" title="Payment methods" sub="Stripe · test mode (MOCKED)" colors={colors} styles={styles} />
          <SectionRow icon="location-outline" title="Service area" sub="Georgia Southern · Savannah" colors={colors} styles={styles} />
          <SectionRow icon="shield-checkmark-outline" title="Safety" sub="Ride tips & rules" colors={colors} styles={styles} />
          <SectionRow icon="help-circle-outline" title="Support" sub="Get help fast" colors={colors} styles={styles} last />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Ride stats</Text>
          <View style={styles.statsRow}>
            <View style={styles.statBox}><Text style={styles.statValue}>—</Text><Text style={styles.statLabel}>Total rides</Text></View>
            <View style={styles.statBox}><Text style={styles.statValue}>—</Text><Text style={styles.statLabel}>Miles ridden</Text></View>
            <View style={styles.statBox}><Text style={styles.statValue}>—</Text><Text style={styles.statLabel}>CO₂ saved</Text></View>
          </View>
        </View>

        <Pressable testID="signout-button" onPress={onSignOut} style={({ pressed }) => [styles.signOutBtn, pressed && { opacity: 0.85 }]}>
          <Ionicons name="log-out-outline" size={20} color={colors.error} />
          <Text style={styles.signOutText}>Sign out</Text>
        </Pressable>

        <Text style={styles.footer}>Swoop v1.0 · Made for Georgia Southern</Text>
      </ScrollView>
    </View>
  );
}

function SectionRow({ icon, title, sub, colors, styles, last }: any) {
  return (
    <Pressable style={[styles.rowBtn, last && { borderBottomWidth: 0 }]}>
      <View style={styles.rowIcon}><Ionicons name={icon} size={20} color={colors.onSurface} /></View>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle}>{title}</Text>
        <Text style={styles.rowSub}>{sub}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  );
}

function SegBtn({ label, active, onPress, testID, colors }: any) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      style={({ pressed }) => [
        {
          flex: 1,
          paddingVertical: 10,
          borderRadius: radius.pill,
          alignItems: "center",
          backgroundColor: active ? colors.brand : "transparent",
          borderWidth: 1,
          borderColor: active ? colors.brand : colors.border,
        },
        pressed && { opacity: 0.85 },
      ]}
    >
      <Text style={{ color: active ? colors.onBrandPrimary : colors.onSurface, fontWeight: "700", fontSize: 13 }}>
        {label}
      </Text>
    </Pressable>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  container: { padding: spacing.lg, gap: spacing.lg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: c.border },
  title: { fontSize: 20, fontWeight: "800", color: c.onSurface },
  avatarBox: { alignItems: "center", gap: spacing.xs, marginVertical: spacing.md },
  avatar: { width: 88, height: 88, borderRadius: 44, backgroundColor: c.brand, alignItems: "center", justifyContent: "center", ...shadow.card },
  avatarText: { fontSize: 40, fontWeight: "800", color: c.onBrandPrimary },
  name: { fontSize: 20, fontWeight: "800", color: c.onSurface, marginTop: spacing.sm },
  email: { color: c.muted, fontSize: 13 },
  section: { backgroundColor: c.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, overflow: "hidden" },
  sectionLabel: { fontSize: 13, color: c.muted, fontWeight: "600", padding: spacing.md, textTransform: "uppercase", letterSpacing: 0.5 },
  rowBtn: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: c.border },
  rowIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  rowTitle: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  rowSub: { fontSize: 12, color: c.muted, marginTop: 2 },
  segmentRow: { flexDirection: "row", gap: spacing.sm, padding: spacing.md, paddingTop: 0 },
  statsRow: { flexDirection: "row", padding: spacing.md, gap: spacing.sm },
  statBox: { flex: 1, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, alignItems: "center" },
  statValue: { fontSize: 20, fontWeight: "800", color: c.onSurface },
  statLabel: { fontSize: 11, color: c.muted, marginTop: 2 },
  signOutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: c.surfaceSecondary, padding: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border },
  signOutText: { color: c.error, fontWeight: "700", fontSize: 15 },
  footer: { color: c.muted, fontSize: 12, textAlign: "center", marginTop: spacing.md },
});
