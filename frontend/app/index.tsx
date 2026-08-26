import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet, Text } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/lib/auth";
import { useTheme } from "@/src/lib/theme-context";

export default function Index() {
  const { user, loading } = useAuth();
  const { colors } = useTheme();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (user) router.replace("/(app)/map");
    else router.replace("/(auth)/login");
  }, [user, loading, router]);

  return (
    <View style={[styles.container, { backgroundColor: colors.surface }]} testID="splash-screen">
      <Text style={[styles.brand, { color: colors.onSurface }]}>Swoop</Text>
      <ActivityIndicator color={colors.brand} size="large" style={{ marginTop: 24 }} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: "center", justifyContent: "center" },
  brand: { fontSize: 48, fontWeight: "800", letterSpacing: -1 },
});
