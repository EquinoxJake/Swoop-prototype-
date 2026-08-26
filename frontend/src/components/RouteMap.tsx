import React, { useMemo } from "react";
import { View, StyleSheet } from "react-native";
import MapView, { Polyline, Marker } from "react-native-maps";
import { Ionicons } from "@expo/vector-icons";
import { radius } from "@/src/lib/theme";
import { useTheme } from "@/src/lib/theme-context";

type Props = {
  route: number[][]; // [[lat, lng], ...]
  height?: number;
};

export default function RouteMap({ route, height = 200 }: Props) {
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => makeStyles(colors, height), [colors, height]);

  if (!route || route.length < 2) return null;

  // Compute region bounds
  const lats = route.map((p) => p[0]);
  const lngs = route.map((p) => p[1]);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const midLat = (minLat + maxLat) / 2;
  const midLng = (minLng + maxLng) / 2;
  const latDelta = Math.max(0.003, (maxLat - minLat) * 1.4);
  const lngDelta = Math.max(0.003, (maxLng - minLng) * 1.4);

  const coords = route.map((p) => ({ latitude: p[0], longitude: p[1] }));
  const start = coords[0];
  const end = coords[coords.length - 1];

  return (
    <View style={styles.container}>
      <MapView
        style={StyleSheet.absoluteFill}
        initialRegion={{ latitude: midLat, longitude: midLng, latitudeDelta: latDelta, longitudeDelta: lngDelta }}
        scrollEnabled={false}
        zoomEnabled={false}
        pitchEnabled={false}
        rotateEnabled={false}
        userInterfaceStyle={isDark ? "dark" : "light"}
      >
        <Polyline coordinates={coords} strokeColor={colors.brand} strokeWidth={5} lineCap="round" lineJoin="round" />
        <Marker coordinate={start} anchor={{ x: 0.5, y: 0.5 }}>
          <View style={[styles.pin, { backgroundColor: colors.brandSecondary }]}>
            <Ionicons name="flag" size={12} color={colors.onBrandSecondary} />
          </View>
        </Marker>
        <Marker coordinate={end} anchor={{ x: 0.5, y: 0.5 }}>
          <View style={[styles.pin, { backgroundColor: colors.surfaceInverse }]}>
            <Ionicons name="checkmark" size={14} color={colors.onSurfaceInverse} />
          </View>
        </Marker>
      </MapView>
    </View>
  );
}

const makeStyles = (c: any, height: number) => StyleSheet.create({
  container: {
    height,
    borderRadius: radius.md,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surfaceTertiary,
  },
  pin: {
    width: 26, height: 26, borderRadius: 13,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: "#fff",
  },
});

export const HAS_ROUTE_MAP = true;
