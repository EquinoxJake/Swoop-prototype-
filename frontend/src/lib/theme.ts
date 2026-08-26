// Swoop design tokens — supports light + dark mode
export type ThemeColors = {
  surface: string;
  onSurface: string;
  surfaceSecondary: string;
  onSurfaceSecondary: string;
  surfaceTertiary: string;
  onSurfaceTertiary: string;
  surfaceInverse: string;
  onSurfaceInverse: string;
  brand: string;
  brandPrimary: string;
  onBrandPrimary: string;
  brandSecondary: string;
  onBrandSecondary: string;
  brandTertiary: string;
  onBrandTertiary: string;
  success: string;
  onSuccess: string;
  warning: string;
  onWarning: string;
  error: string;
  onError: string;
  info: string;
  onInfo: string;
  border: string;
  borderStrong: string;
  divider: string;
  muted: string;
};

export const lightColors: ThemeColors = {
  surface: "#F5F7FB",
  onSurface: "#0F172A",
  surfaceSecondary: "#FFFFFF",
  onSurfaceSecondary: "#0F172A",
  surfaceTertiary: "#EDF1F7",
  onSurfaceTertiary: "#0F172A",
  surfaceInverse: "#0F172A",
  onSurfaceInverse: "#FFFFFF",
  brand: "#2E7BFF",
  brandPrimary: "#2E7BFF",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#20B26C",
  onBrandSecondary: "#FFFFFF",
  brandTertiary: "#DBE8FF",
  onBrandTertiary: "#123A99",
  success: "#20B26C",
  onSuccess: "#FFFFFF",
  warning: "#E69109",
  onWarning: "#FFFFFF",
  error: "#D9381E",
  onError: "#FFFFFF",
  info: "#0F172A",
  onInfo: "#FFFFFF",
  border: "#E4E9F2",
  borderStrong: "#CBD3E1",
  divider: "#E4E9F2",
  muted: "#6B7280",
};

export const darkColors: ThemeColors = {
  surface: "#0B0F17",
  onSurface: "#F5F7FA",
  surfaceSecondary: "#131824",
  onSurfaceSecondary: "#F5F7FA",
  surfaceTertiary: "#1B2130",
  onSurfaceTertiary: "#F5F7FA",
  surfaceInverse: "#F5F7FA",
  onSurfaceInverse: "#0B0F17",
  brand: "#4C93FF",
  brandPrimary: "#4C93FF",
  onBrandPrimary: "#0B0F17",
  brandSecondary: "#3AD48D",
  onBrandSecondary: "#0B0F17",
  brandTertiary: "#1E3660",
  onBrandTertiary: "#B7D2FF",
  success: "#3AD48D",
  onSuccess: "#0B0F17",
  warning: "#F0A93A",
  onWarning: "#0B0F17",
  error: "#F1594A",
  onError: "#FFFFFF",
  info: "#F5F7FA",
  onInfo: "#0B0F17",
  border: "#232A3A",
  borderStrong: "#333A4B",
  divider: "#232A3A",
  muted: "#8B929F",
};

// Backwards-compat default (used only where a Provider isn't available yet)
export const colors = lightColors;

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

export function batteryColor(pct: number, c: ThemeColors = lightColors): string {
  if (pct >= 60) return c.success;
  if (pct >= 30) return c.warning;
  return c.error;
}
