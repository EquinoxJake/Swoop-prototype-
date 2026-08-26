import { useMemo, useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/lib/auth";
import { spacing, radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

export default function Login() {
  const router = useRouter();
  const { colors, isDark } = useTheme();
  const { signIn, signInWithGoogle } = useAuth();
  const [email, setEmail] = useState("demo@swoop.app");
  const [password, setPassword] = useState("swoop1234");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const styles = useMemo(() => makeStyles(colors), [colors]);

  const onSubmit = async () => {
    setErr(null); setLoading(true);
    try { await signIn(email.trim(), password); router.replace("/(app)/map"); }
    catch (e: any) { setErr(e.message || "Login failed"); }
    finally { setLoading(false); }
  };
  const onGoogle = async () => {
    setErr(null); setLoading(true);
    try { await signInWithGoogle(); router.replace("/(app)/map"); }
    catch (e: any) { setErr(e.message || "Google sign-in failed"); }
    finally { setLoading(false); }
  };

  const heroColors: [string, string, string] = isDark
    ? [colors.brand, "#1E3660", colors.surface]
    : [colors.brand, "#7FB0FF", colors.surface];

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.surface }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
      <LinearGradient colors={heroColors} style={styles.hero}>
        <Text style={styles.brand} testID="brand-title">Swoop</Text>
        <Text style={styles.tagline}>Ride the campus. Own the streets.</Text>
      </LinearGradient>
      <ScrollView contentContainerStyle={styles.form} keyboardShouldPersistTaps="handled">
        <Text style={styles.h1}>Welcome back</Text>
        <Text style={styles.h2}>Sign in to grab a scooter</Text>
        <View style={styles.inputWrap}>
          <Ionicons name="mail-outline" size={18} color={colors.muted} />
          <TextInput testID="login-email-input" value={email} onChangeText={setEmail} placeholder="you@school.edu" placeholderTextColor={colors.muted} style={styles.input} autoCapitalize="none" keyboardType="email-address" />
        </View>
        <View style={styles.inputWrap}>
          <Ionicons name="lock-closed-outline" size={18} color={colors.muted} />
          <TextInput testID="login-password-input" value={password} onChangeText={setPassword} placeholder="Password" placeholderTextColor={colors.muted} style={styles.input} secureTextEntry />
        </View>
        {err && <Text style={styles.error} testID="login-error">{err}</Text>}
        <Pressable testID="login-submit-button" onPress={onSubmit} disabled={loading} style={({ pressed }) => [styles.primary, pressed && { opacity: 0.85 }]}>
          {loading ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.primaryText}>Sign in</Text>}
        </Pressable>
        <View style={styles.divider}>
          <View style={styles.line} /><Text style={styles.dividerText}>or</Text><View style={styles.line} />
        </View>
        <Pressable testID="login-google-button" onPress={onGoogle} style={({ pressed }) => [styles.googleBtn, pressed && { opacity: 0.85 }]}>
          <Ionicons name="logo-google" size={20} color={colors.onSurface} />
          <Text style={styles.googleText}>Continue with Google</Text>
        </Pressable>
        <Pressable testID="login-signup-link" onPress={() => router.push("/(auth)/signup")} style={styles.linkWrap}>
          <Text style={styles.link}>New to Swoop? <Text style={{ fontWeight: "700" }}>Create account</Text></Text>
        </Pressable>
        <Text style={styles.footer}>Demo: demo@swoop.app / swoop1234</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: any) => StyleSheet.create({
  hero: { paddingTop: 80, paddingBottom: spacing.xxl, paddingHorizontal: spacing.xl, alignItems: "flex-start" },
  brand: { fontSize: 56, fontWeight: "800", color: "#FFFFFF", letterSpacing: -2 },
  tagline: { fontSize: 15, color: "#FFFFFF", opacity: 0.9, marginTop: spacing.xs },
  form: { padding: spacing.xl, gap: spacing.md, paddingBottom: 60 },
  h1: { fontSize: 26, fontWeight: "700", color: c.onSurface },
  h2: { fontSize: 14, color: c.muted, marginBottom: spacing.md },
  inputWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: 14, borderWidth: 1, borderColor: c.border },
  input: { flex: 1, fontSize: 16, color: c.onSurface },
  primary: { backgroundColor: c.brand, borderRadius: radius.pill, paddingVertical: 18, alignItems: "center", marginTop: spacing.sm, ...shadow.card },
  primaryText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 16 },
  divider: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginVertical: spacing.md },
  line: { flex: 1, height: 1, backgroundColor: c.border },
  dividerText: { color: c.muted, fontSize: 13 },
  googleBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: c.surfaceSecondary, borderRadius: radius.pill, paddingVertical: 16, borderWidth: 1, borderColor: c.border },
  googleText: { color: c.onSurface, fontWeight: "600", fontSize: 15 },
  linkWrap: { alignItems: "center", marginTop: spacing.md },
  link: { color: c.onSurface, fontSize: 14 },
  error: { color: c.error, fontSize: 13, textAlign: "center" },
  footer: { color: c.muted, fontSize: 12, textAlign: "center", marginTop: spacing.md },
});
