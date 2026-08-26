import React from "react";
import { View, Text, StyleSheet } from "react-native";
import MapView, { Marker } from "react-native-maps";
import { Ionicons } from "@expo/vector-icons";
import { Scooter } from "@/src/lib/api";
import { colors, radius, shadow } from "@/src/lib/theme";

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
  return (
    <MapView
      ref={mapRef}
      style={StyleSheet.absoluteFill}
      initialRegion={DEFAULT_REGION}
      showsUserLocation
      showsMyLocationButton={false}
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

export const IS_NATIVE_MAP = true;
