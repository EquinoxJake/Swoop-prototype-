import { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, PaymentMethod } from "@/src/lib/api";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

function formatCardNumber(v: string) {
  const digits = v.replace(/\D/g, "").slice(0, 19);
  return digits.replace(/(.{4})/g, "$1 ").trim();
}
function formatExp(v: string) {
  const digits = v.replace(/\D/g, "").slice(0, 4);
  if (digits.length <= 2) return digits;
  return `${digits.slice(0, 2)}/${digits.slice(2)}`;
}

export default function PaymentMethodScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  const params = useLocalSearchParams<{ reserve_after?: string }>();
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const [cards, setCards] = useState<PaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [number, setNumber] = useState("4242 4242 4242 4242");
  const [exp, setExp] = useState("12/30");
  const [cvc, setCvc] = useState("123");
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try { setCards(await api.listPaymentMethods()); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { if (!loading && cards.length === 0) setShowForm(true); }, [loading, cards.length]);

  const save = async () => {
    setErr(null); setSaving(true);
    try {
      const digits = number.replace(/\s/g, "");
      const [mm, yy] = exp.split("/");
      if (!mm || !yy) throw new Error("Invalid expiration");
      const year = yy.length === 2 ? 2000 + parseInt(yy, 10) : parseInt(yy, 10);
      await api.addPaymentMethod(digits, parseInt(mm, 10), year, cvc);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setShowForm(false); setNumber(""); setExp(""); setCvc("");
      await load();
      // If we came here to reserve a scooter, go straight into the ride
      if (params.reserve_after) {
        try {
          const ride = await api.reserveRide(String(params.reserve_after));
          router.replace(`/(app)/ride?ride_id=${ride.ride_id}`);
          return;
        } catch (e: any) { setErr(e.message || "Could not reserve"); }
      }
    } catch (e: any) {
      setErr(e.message || "Failed to save card");
    } finally { setSaving(false); }
  };

  const remove = async (id: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try { await api.deletePaymentMethod(id); await load(); } catch {}
  };
  const makeDefault = async (id: string) => {
    Haptics.selectionAsync();
    try { await api.setDefaultPaymentMethod(id); await load(); } catch {}
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.surface }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
      <ScrollView contentContainerStyle={[styles.container, { paddingTop: insets.top + spacing.md, paddingBottom: insets.bottom + spacing.xl }]}>
        <View style={styles.header}>
          <Pressable testID="pm-close" onPress={() => router.back()} style={styles.backBtn}>
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.title}>Payment</Text>
          <View style={{ width: 40 }} />
        </View>

        {params.reserve_after && (
          <View style={styles.notice} testID="pm-required-notice">
            <Ionicons name="information-circle" size={20} color={colors.brand} />
            <Text style={styles.noticeText}>
              Add a card to unlock scooter {params.reserve_after}. We'll charge $1.00 to unlock, then $0.20 per mile as you ride.
            </Text>
          </View>
        )}

        {/* Cards list */}
        {loading ? (
          <ActivityIndicator color={colors.brand} style={{ marginTop: 40 }} />
        ) : (
          cards.map((c) => (
            <View key={c.payment_method_id} style={styles.card} testID={`pm-card-${c.last4}`}>
              <View style={styles.cardTop}>
                <View style={styles.brandBox}>
                  <Text style={styles.brandText}>{c.brand}</Text>
                </View>
                {c.is_default && (
                  <View style={styles.defaultPill}><Text style={styles.defaultText}>Default</Text></View>
                )}
              </View>
              <Text style={styles.cardNumber}>•••• •••• •••• {c.last4}</Text>
              <Text style={styles.cardExp}>Expires {String(c.exp_month).padStart(2, "0")}/{String(c.exp_year).slice(-2)}</Text>
              <View style={styles.cardActions}>
                {!c.is_default && (
                  <Pressable testID={`pm-set-default-${c.last4}`} onPress={() => makeDefault(c.payment_method_id)} style={styles.cardAction}>
                    <Text style={styles.cardActionText}>Set default</Text>
                  </Pressable>
                )}
                <Pressable testID={`pm-remove-${c.last4}`} onPress={() => remove(c.payment_method_id)} style={styles.cardAction}>
                  <Text style={[styles.cardActionText, { color: colors.error }]}>Remove</Text>
                </Pressable>
              </View>
            </View>
          ))
        )}

        {/* Add card form */}
        {showForm ? (
          <View style={styles.form}>
            <Text style={styles.formTitle}>Add card</Text>
            <View style={styles.inputWrap}>
              <Ionicons name="card-outline" size={18} color={colors.muted} />
              <TextInput
                testID="pm-number-input"
                value={number}
                onChangeText={(v) => setNumber(formatCardNumber(v))}
                placeholder="1234 5678 9012 3456"
                placeholderTextColor={colors.muted}
                style={styles.input}
                keyboardType="number-pad"
              />
            </View>
            <View style={styles.row}>
              <View style={[styles.inputWrap, { flex: 1 }]}>
                <Ionicons name="calendar-outline" size={18} color={colors.muted} />
                <TextInput
                  testID="pm-exp-input"
                  value={exp}
                  onChangeText={(v) => setExp(formatExp(v))}
                  placeholder="MM/YY"
                  placeholderTextColor={colors.muted}
                  style={styles.input}
                  keyboardType="number-pad"
                />
              </View>
              <View style={[styles.inputWrap, { flex: 1 }]}>
                <Ionicons name="lock-closed-outline" size={18} color={colors.muted} />
                <TextInput
                  testID="pm-cvc-input"
                  value={cvc}
                  onChangeText={(v) => setCvc(v.replace(/\D/g, "").slice(0, 4))}
                  placeholder="CVC"
                  placeholderTextColor={colors.muted}
                  style={styles.input}
                  keyboardType="number-pad"
                  secureTextEntry
                />
              </View>
            </View>
            <Text style={styles.testHint}>Test mode — MOCKED. No real charge is made. Try 4242 4242 4242 4242.</Text>
            {err && <Text style={styles.error} testID="pm-error">{err}</Text>}
            <Pressable
              testID="pm-save-button"
              onPress={save}
              disabled={saving}
              style={({ pressed }) => [styles.primary, pressed && { opacity: 0.9 }, saving && { opacity: 0.6 }]}
            >
              {saving ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.primaryText}>Save card</Text>}
            </Pressable>
            {cards.length > 0 && (
              <Pressable onPress={() => setShowForm(false)} style={{ alignItems: "center", marginTop: spacing.sm }}>
                <Text style={{ color: colors.muted }}>Cancel</Text>
              </Pressable>
            )}
          </View>
        ) : (
          <Pressable
            testID="pm-add-button"
            onPress={() => setShowForm(true)}
            style={({ pressed }) => [styles.addBtn, pressed && { opacity: 0.85 }]}
          >
            <Ionicons name="add" size={22} color={colors.brand} />
            <Text style={styles.addText}>Add a new card</Text>
          </Pressable>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  container: { padding: spacing.lg, gap: spacing.md },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: c.border },
  title: { fontSize: 20, fontWeight: "800", color: c.onSurface },
  notice: { flexDirection: "row", gap: spacing.sm, backgroundColor: c.brandTertiary, padding: spacing.md, borderRadius: radius.md, alignItems: "flex-start" },
  noticeText: { flex: 1, color: c.onBrandTertiary, fontSize: 13, lineHeight: 18 },
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl, borderWidth: 1, borderColor: c.border, ...shadow.card, gap: spacing.sm },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  brandBox: { backgroundColor: c.surfaceInverse, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.sm },
  brandText: { color: c.onSurfaceInverse, fontWeight: "800", fontSize: 12, letterSpacing: 0.5 },
  defaultPill: { backgroundColor: c.brand, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  defaultText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 },
  cardNumber: { fontSize: 22, fontWeight: "700", color: c.onSurface, letterSpacing: 2, fontVariant: ["tabular-nums"] as any, marginTop: spacing.sm },
  cardExp: { color: c.muted, fontSize: 13 },
  cardActions: { flexDirection: "row", gap: spacing.md, marginTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.border, paddingTop: spacing.md },
  cardAction: {},
  cardActionText: { color: c.onSurface, fontWeight: "700", fontSize: 13 },

  form: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl, gap: spacing.md, borderWidth: 1, borderColor: c.border },
  formTitle: { fontSize: 18, fontWeight: "800", color: c.onSurface },
  inputWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: 14 },
  input: { flex: 1, fontSize: 16, color: c.onSurface },
  row: { flexDirection: "row", gap: spacing.sm },
  testHint: { color: c.muted, fontSize: 12, textAlign: "center" },
  primary: { backgroundColor: c.brand, borderRadius: radius.pill, paddingVertical: 18, alignItems: "center", ...shadow.card },
  primaryText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 16 },
  error: { color: c.error, fontSize: 13, textAlign: "center" },

  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, padding: spacing.lg, backgroundColor: c.surfaceSecondary, borderWidth: 2, borderColor: c.brand, borderStyle: "dashed", borderRadius: radius.md },
  addText: { color: c.brand, fontWeight: "800", fontSize: 15 },
});
