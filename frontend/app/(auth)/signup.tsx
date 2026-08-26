import { useMemo, useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/lib/auth";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

export default function Signup() {
  const router = useRouter();
  const { colors } = useTheme();
  const { signUp } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const onSubmit = async () => {
    setErr(null);
    if (password.length < 6) { setErr("Password must be at least 6 characters"); return; }
    setLoading(true);
    try { await signUp(email.trim(), password, name.trim() || undefined); router.replace("/(app)/map"); }
    catch (e: any) { setErr(e.message || "Signup failed"); }
    finally { setLoading(false); }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.surface }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
      <ScrollView contentContainerStyle={styles.form} keyboardShouldPersistTaps="handled">
        <Pressable testID="signup-back-button" onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.h1}>Create your Swoop account</Text>
        <Text style={styles.h2}>Unlock scooters at Georgia Southern & Savannah</Text>
        <View style={styles.inputWrap}>
          <Ionicons name="person-outline" size={18} color={colors.muted} />
          <TextInput testID="signup-name-input" value={name} onChangeText={setName} placeholder="Your name" placeholderTextColor={colors.muted} style={styles.input} />
        </View>
        <View style={styles.inputWrap}>
          <Ionicons name="mail-outline" size={18} color={colors.muted} />
          <TextInput testID="signup-email-input" value={email} onChangeText={setEmail} placeholder="you@school.edu" placeholderTextColor={colors.muted} style={styles.input} autoCapitalize="none" keyboardType="email-address" />
        </View>
        <View style={styles.inputWrap}>
          <Ionicons name="lock-closed-outline" size={18} color={colors.muted} />
          <TextInput testID="signup-password-input" value={password} onChangeText={setPassword} placeholder="Password (min 6 chars)" placeholderTextColor={colors.muted} style={styles.input} secureTextEntry />
        </View>
        {err && <Text style={styles.error} testID="signup-error">{err}</Text>}
        <Pressable testID="signup-submit-button" onPress={onSubmit} disabled={loading} style={({ pressed }) => [styles.primary, pressed && { opacity: 0.85 }]}>
          {loading ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.primaryText}>Create account</Text>}
        </Pressable>
        <Pressable onPress={() => router.replace("/(auth)/login")} testID="signup-login-link" style={{ alignItems: "center", marginTop: spacing.md }}>
          <Text style={{ color: colors.onSurface }}>Already have an account? <Text style={{ fontWeight: "700" }}>Sign in</Text></Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  form: { padding: spacing.xl, paddingTop: 80, gap: spacing.md, flexGrow: 1 },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: c.border, marginBottom: spacing.md },
  h1: { fontSize: 28, fontWeight: "800", color: c.onSurface, letterSpacing: -0.5 },
  h2: { fontSize: 14, color: c.muted, marginBottom: spacing.lg },
  inputWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: 14, borderWidth: 1, borderColor: c.border },
  input: { flex: 1, fontSize: 16, color: c.onSurface },
  primary: { backgroundColor: c.brand, borderRadius: radius.pill, paddingVertical: 18, alignItems: "center", marginTop: spacing.sm, ...shadow.card },
  primaryText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 16 },
  error: { color: c.error, fontSize: 13, textAlign: "center" },
});
