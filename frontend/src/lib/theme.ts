// Swoop design tokens (from /app/design_guidelines.json)
export const colors = {
  surface: "#F7F5F0",
  onSurface: "#1A1A1A",
  surfaceSecondary: "#FFFFFF",
  onSurfaceSecondary: "#1A1A1A",
  surfaceTertiary: "#EAE6DF",
  onSurfaceTertiary: "#1A1A1A",
  surfaceInverse: "#222222",
  onSurfaceInverse: "#FFFFFF",
  brand: "#F3A712",
  brandPrimary: "#F3A712",
  onBrandPrimary: "#111111",
  brandSecondary: "#20B26C",
  onBrandSecondary: "#FFFFFF",
  brandTertiary: "#FCE5BA",
  onBrandTertiary: "#734F08",
  success: "#20B26C",
  onSuccess: "#FFFFFF",
  warning: "#E69109",
  onWarning: "#FFFFFF",
  error: "#D9381E",
  onError: "#FFFFFF",
  info: "#1A1A1A",
  onInfo: "#FFFFFF",
  border: "#EAE6DF",
  borderStrong: "#D1C9BC",
  divider: "#EAE6DF",
  muted: "#6B6B6B",
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
};

export const radius = {
  sm: 8,
  md: 16,
  lg: 24,
  pill: 999,
};

export const font = {
  display: "Outfit_600SemiBold", // fallback to system if not loaded
  text: "System",
};

export const shadow = {
  card: {
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 4,
  },
  floating: {
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.16,
    shadowRadius: 20,
    elevation: 8,
  },
};

export function batteryColor(pct: number): string {
  if (pct >= 60) return colors.success;
  if (pct >= 30) return colors.warning;
  return colors.error;
}
