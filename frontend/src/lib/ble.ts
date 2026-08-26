// Native BLE wrapper. Falls back to a no-op stub in Expo Go / web via ble.web.tsx.
// react-native-ble-plx REQUIRES a dev build — Expo Go will throw when the native
// module isn't present, so we wrap every import in a try/require.
import { Platform } from "react-native";
import Constants from "expo-constants";

let _mgr: any = null;
let _importFailed = false;

function loadManager(): any {
  if (_mgr) return _mgr;
  if (_importFailed) return null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { BleManager } = require("react-native-ble-plx");
    _mgr = new BleManager();
    return _mgr;
  } catch (e) {
    _importFailed = true;
    return null;
  }
}

// Expo Go doesn't ship the native module. Detect and refuse politely.
export const IS_EXPO_GO = Constants.appOwnership === "expo";
export const HAS_BLE = Platform.OS !== "web" && !IS_EXPO_GO;

export type Advertisement = {
  id: string;             // device id (iOS UUID / Android MAC)
  name: string | null;
  rssi: number | null;
  manufacturerData: string | null; // base64
  serviceUUIDs: string[] | null;
  isConnectable: boolean | null;
};

export type BleService = {
  uuid: string;
  isPrimary: boolean;
  characteristics: { uuid: string; isWritable: boolean; isReadable: boolean; isNotifiable: boolean }[];
};

export async function ensureReady(): Promise<{ ok: boolean; reason?: string }> {
  if (!HAS_BLE) return { ok: false, reason: IS_EXPO_GO ? "BLE isn't available in Expo Go — generate a dev build" : "BLE isn't available on this platform" };
  const mgr = loadManager();
  if (!mgr) return { ok: false, reason: "BLE module failed to load" };
  return new Promise((resolve) => {
    const sub = mgr.onStateChange((state: string) => {
      if (state === "PoweredOn") { sub.remove(); resolve({ ok: true }); }
      else if (state === "PoweredOff") { sub.remove(); resolve({ ok: false, reason: "Bluetooth is off" }); }
      else if (state === "Unauthorized") { sub.remove(); resolve({ ok: false, reason: "Bluetooth permission denied" }); }
    }, true);
    // Fallback timeout
    setTimeout(() => { try { sub.remove(); } catch {}; resolve({ ok: false, reason: "BLE state check timed out" }); }, 6000);
  });
}

export function startScan(onDevice: (d: Advertisement) => void, options?: { serviceUUIDs?: string[] | null }) {
  const mgr = loadManager();
  if (!mgr) return () => {};
  mgr.startDeviceScan(options?.serviceUUIDs || null, { allowDuplicates: false }, (err: any, device: any) => {
    if (err || !device) return;
    onDevice({
      id: device.id,
      name: device.name || device.localName || null,
      rssi: device.rssi ?? null,
      manufacturerData: device.manufacturerData || null,
      serviceUUIDs: device.serviceUUIDs || null,
      isConnectable: device.isConnectable ?? null,
    });
  });
  return () => { try { mgr.stopDeviceScan(); } catch {} };
}

export async function connect(deviceId: string) {
  const mgr = loadManager();
  if (!mgr) throw new Error("BLE unavailable");
  const dev = await mgr.connectToDevice(deviceId, { requestMTU: 185 });
  await dev.discoverAllServicesAndCharacteristics();
  return dev;
}

export async function listServices(device: any): Promise<BleService[]> {
  const services = await device.services();
  const out: BleService[] = [];
  for (const s of services) {
    const chs = await s.characteristics();
    out.push({
      uuid: s.uuid,
      isPrimary: s.isPrimary,
      characteristics: chs.map((c: any) => ({
        uuid: c.uuid,
        isWritable: !!(c.isWritableWithResponse || c.isWritableWithoutResponse),
        isReadable: !!c.isReadable,
        isNotifiable: !!c.isNotifiable,
      })),
    });
  }
  return out;
}

export async function writeHex(device: any, serviceUUID: string, charUUID: string, hex: string, withResponse = true) {
  const b64 = Buffer.from(hex, "hex").toString("base64");
  if (withResponse) return device.writeCharacteristicWithResponseForService(serviceUUID, charUUID, b64);
  return device.writeCharacteristicWithoutResponseForService(serviceUUID, charUUID, b64);
}

export function subscribeHex(device: any, serviceUUID: string, charUUID: string, onValue: (hex: string) => void) {
  const sub = device.monitorCharacteristicForService(serviceUUID, charUUID, (err: any, ch: any) => {
    if (err || !ch?.value) return;
    onValue(Buffer.from(ch.value, "base64").toString("hex"));
  });
  return () => { try { sub.remove(); } catch {} };
}

export async function disconnect(device: any) {
  try { await device.cancelConnection(); } catch {}
}
