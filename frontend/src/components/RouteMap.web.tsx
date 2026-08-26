import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { radius, spacing } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

type Props = { route: number[][]; height?: number };

// Web fallback: simple placeholder — real map is native-only
export default function RouteMap({ route, height = 200 }: Props) {
  const { colors } = useTheme();
  return (
    <View style={[styles.container, { height, backgroundColor: colors.surfaceTertiary, borderColor: colors.border }]}>
      <Ionicons name="map-outline" size={26} color={colors.muted} />
      <Text style={[styles.text, { color: colors.muted }]}>
        Route saved ({route?.length ?? 0} points) — visible on your phone
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    borderWidth: 1,
  },
  text: { fontSize: 12, textAlign: "center", paddingHorizontal: spacing.lg },
});

export const HAS_ROUTE_MAP = false;
