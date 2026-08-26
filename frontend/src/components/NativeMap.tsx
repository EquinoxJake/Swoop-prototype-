import React, { useMemo } from "react";
import { View, Text, StyleSheet } from "react-native";
import MapView, { Marker } from "react-native-maps";
import { Ionicons } from "@expo/vector-icons";
import { Scooter } from "@/src/lib/api";
import { radius, shadow } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

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

export default function NativeMap({ scooters, onPinPress, mapRef }: Props) {
  const { colors, isDark } = useTheme();
  const pinStyles = useMemo(() => makePinStyles(colors), [colors]);
  return (
    <MapView
      ref={mapRef}
      style={StyleSheet.absoluteFill}
      initialRegion={DEFAULT_REGION}
      showsUserLocation
      showsMyLocationButton={false}
      userInterfaceStyle={isDark ? "dark" : "light"}
    >
      {scooters.map((s) => (
        <Marker
          key={s.scooter_id}
          coordinate={{ latitude: s.lat, longitude: s.lng }}
          onPress={() => onPinPress(s)}
          tracksViewChanges={false}
        >
          <View style={[pinStyles.pin, s.status !== "available" && { opacity: 0.4 }]}>
            <Ionicons name="flash" size={14} color={colors.onBrandPrimary} />
            <Text style={pinStyles.pinText}>{s.battery}%</Text>
          </View>
        </Marker>
      ))}
    </MapView>
  );
}

const makePinStyles = (c: any) => StyleSheet.create({
  pin: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: c.brand,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: "#fff",
    ...shadow.card,
  },
  pinText: { color: c.onBrandPrimary, fontWeight: "800", fontSize: 12 },
});

export const IS_NATIVE_MAP = true;
