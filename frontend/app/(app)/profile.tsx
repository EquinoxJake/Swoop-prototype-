import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "@/src/lib/auth";
import { colors, spacing, radius, shadow } from "@/src/lib/theme";

export default function Profile() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user, signOut } = useAuth();

  const onSignOut = async () => {
    await signOut();
    router.replace("/(auth)/login");
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

        <View style={styles.section}>
          <SectionRow icon="card-outline" title="Payment methods" sub="Stripe · test mode (MOCKED)" />
          <SectionRow icon="location-outline" title="Service area" sub="Georgia Southern · Savannah" />
          <SectionRow icon="shield-checkmark-outline" title="Safety" sub="Ride tips & rules" />
          <SectionRow icon="help-circle-outline" title="Support" sub="Get help fast" />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Ride stats</Text>
          <View style={styles.statsRow}>
            <View style={styles.statBox}>
              <Text style={styles.statValue}>—</Text>
              <Text style={styles.statLabel}>Total rides</Text>
            </View>
            <View style={styles.statBox}>
              <Text style={styles.statValue}>—</Text>
              <Text style={styles.statLabel}>Miles ridden</Text>
            </View>
            <View style={styles.statBox}>
              <Text style={styles.statValue}>—</Text>
              <Text style={styles.statLabel}>CO₂ saved</Text>
            </View>
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

function SectionRow({ icon, title, sub }: any) {
  return (
    <Pressable style={styles.rowBtn}>
      <View style={styles.rowIcon}>
        <Ionicons name={icon} size={20} color={colors.onSurface} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle}>{title}</Text>
        <Text style={styles.rowSub}>{sub}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { padding: spacing.lg, gap: spacing.lg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  backBtn: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border,
  },
  title: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  avatarBox: { alignItems: "center", gap: spacing.xs, marginVertical: spacing.md },
  avatar: {
    width: 88, height: 88, borderRadius: 44,
    backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
    ...shadow.card,
  },
  avatarText: { fontSize: 40, fontWeight: "800", color: colors.onBrandPrimary },
  name: { fontSize: 20, fontWeight: "800", color: colors.onSurface, marginTop: spacing.sm },
  email: { color: colors.muted, fontSize: 13 },
  section: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    overflow: "hidden",
  },
  sectionLabel: { fontSize: 13, color: colors.muted, fontWeight: "600", padding: spacing.md, textTransform: "uppercase", letterSpacing: 0.5 },
  rowBtn: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  rowIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center", justifyContent: "center",
  },
  rowTitle: { fontSize: 15, fontWeight: "600", color: colors.onSurface },
  rowSub: { fontSize: 12, color: colors.muted, marginTop: 2 },
  statsRow: { flexDirection: "row", padding: spacing.md, gap: spacing.sm },
  statBox: { flex: 1, backgroundColor: colors.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, alignItems: "center" },
  statValue: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  statLabel: { fontSize: 11, color: colors.muted, marginTop: 2 },
  signOutBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    padding: spacing.lg, borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
  },
  signOutText: { color: colors.error, fontWeight: "700", fontSize: 15 },
  footer: { color: colors.muted, fontSize: 12, textAlign: "center", marginTop: spacing.md },
});
