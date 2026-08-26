import React from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Scooter } from "@/src/lib/api";
import { colors, radius, shadow, spacing } from "@/src/lib/theme";

export const DEFAULT_REGION = {
  latitude: 32.4171,
  longitude: -81.7784,
  latitudeDelta: 0.03,
  longitudeDelta: 0.03,
};

type Props = {
  scooters: Scooter[];
  onPinPress: (s: Scooter) => void;
  mapRef?: React.MutableRefObject<any>;
};

// Web fallback: styled list of scooters (no native map on web preview)
export default function NativeMap({ scooters, onPinPress }: Props) {
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.surfaceTertiary }}
      contentContainerStyle={{ padding: spacing.xl, paddingTop: 130, paddingBottom: 200 }}
    >
      <Text style={{ fontSize: 22, fontWeight: "800", color: colors.onSurface, marginBottom: 4 }}>
        Nearby scooters
      </Text>
      <Text style={{ color: colors.muted, marginBottom: spacing.lg, fontSize: 13 }}>
        Live map preview — open on device for GPS map
      </Text>
      {scooters.map((s) => (
        <Pressable
          key={s.scooter_id}
          testID={`web-scooter-${s.code}`}
          onPress={() => onPinPress(s)}
          style={webStyles.card}
        >
          <View style={pinStyles.pin}>
            <Ionicons name="flash" size={14} color={colors.onBrandPrimary} />
            <Text style={pinStyles.pinText}>{s.battery}%</Text>
          </View>
          <View style={{ flex: 1, marginLeft: spacing.md }}>
            <Text style={{ fontWeight: "700", fontSize: 16, color: colors.onSurface }}>{s.code}</Text>
            <Text style={{ color: colors.muted, fontSize: 13 }}>{s.model} · {s.status}</Text>
          </View>
          <Ionicons name="chevron-forward" size={20} color={colors.muted} />
        </Pressable>
      ))}
    </ScrollView>
  );
}

const pinStyles = StyleSheet.create({
  pin: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brand,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: "#fff",
    ...shadow.card,
  },
  pinText: { color: colors.onBrandPrimary, fontWeight: "800", fontSize: 12 },
});

const webStyles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surfaceSecondary,
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
});

export const IS_NATIVE_MAP = false;
