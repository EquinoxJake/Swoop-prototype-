// Web stub — BLE is not available in the browser preview.
export const IS_EXPO_GO = false;
export const HAS_BLE = false;

export type Advertisement = { id: string; name: string | null; rssi: number | null; manufacturerData: string | null; serviceUUIDs: string[] | null; isConnectable: boolean | null };
export type BleService = { uuid: string; isPrimary: boolean; characteristics: { uuid: string; isWritable: boolean; isReadable: boolean; isNotifiable: boolean }[] };

export async function ensureReady() { return { ok: false, reason: "BLE isn't available in the web preview — open Swoop in a dev build on your phone" }; }
export function startScan(_onDevice: any, _o?: any) { return () => {}; }
export async function connect(_id: string): Promise<any> { throw new Error("BLE unavailable on web"); }
export async function listServices(_d: any): Promise<BleService[]> { return []; }
export async function writeHex(..._args: any[]) { throw new Error("BLE unavailable"); }
export function subscribeHex(..._args: any[]) { return () => {}; }
export async function disconnect(_d: any) {}
