import { Stack, useRouter } from "expo-router";
import { useEffect } from "react";
import { View, ActivityIndicator } from "react-native";
import { useAuth } from "@/src/lib/auth";
import { useTheme } from "@/src/lib/theme-context";

export default function AppLayout() {
  const { user, loading } = useAuth();
  const { colors } = useTheme();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/(auth)/login");
  }, [user, loading, router]);

  if (loading || !user) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface }}>
        <ActivityIndicator color={colors.brand} size="large" />
      </View>
    );
  }

  return (
    <Stack screenOptions={{ headerShown: false, animation: "slide_from_right", contentStyle: { backgroundColor: colors.surface } }}>
      <Stack.Screen name="map" />
      <Stack.Screen name="scan" options={{ presentation: "modal" }} />
      <Stack.Screen name="ride" />
      <Stack.Screen name="receipt" />
      <Stack.Screen name="history" options={{ presentation: "modal" }} />
      <Stack.Screen name="profile" options={{ presentation: "modal" }} />
    </Stack>
  );
}
