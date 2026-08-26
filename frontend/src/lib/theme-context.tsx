import React, { createContext, useContext, useEffect, useState, useCallback, useMemo } from "react";
import { useColorScheme } from "react-native";
import { storage } from "@/src/utils/storage";
import { lightColors, darkColors, ThemeColors } from "./theme";

export type ThemeMode = "light" | "dark" | "system";

type ThemeCtx = {
  mode: ThemeMode; // user preference
  isDark: boolean; // resolved
  colors: ThemeColors;
  setMode: (m: ThemeMode) => Promise<void>;
  toggle: () => Promise<void>;
};

const Ctx = createContext<ThemeCtx | undefined>(undefined);
const KEY = "swoop_theme_mode";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const system = useColorScheme();
  const [mode, setModeState] = useState<ThemeMode>("system");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      const stored = await storage.getItem<string>(KEY, "system");
      if (stored === "light" || stored === "dark" || stored === "system") {
        setModeState(stored);
      }
      setLoaded(true);
    })();
  }, []);

  const isDark = mode === "system" ? system === "dark" : mode === "dark";
  const colors = isDark ? darkColors : lightColors;

  const setMode = useCallback(async (m: ThemeMode) => {
    setModeState(m);
    await storage.setItem(KEY, m);
  }, []);

  const toggle = useCallback(async () => {
    const next: ThemeMode = isDark ? "light" : "dark";
    await setMode(next);
  }, [isDark, setMode]);

  const value = useMemo(() => ({ mode, isDark, colors, setMode, toggle }), [mode, isDark, colors, setMode, toggle]);

  if (!loaded) return null;
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useTheme must be within ThemeProvider");
  return c;
}
