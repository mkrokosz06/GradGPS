import api from "./api";

export interface AppConfig {
  min_supported_version: string;
  latest_version: string;
  ios_update_url: string;
}

/** Public launch-time config. Drives the version gate (UpdateGate). */
export async function fetchAppConfig(): Promise<AppConfig> {
  const { data } = await api.get<AppConfig>("/config/app");
  return data;
}

/**
 * Compare two dotted version strings ("1.2.3"). Returns -1 if a < b, 0 if
 * equal, 1 if a > b. Missing/garbage components are treated as 0, so it's
 * safe on partial versions and the "0.0.0" fail-open defaults.
 */
export function cmpVersions(a: string, b: string): number {
  const pa = a.split(".").map((n) => parseInt(n, 10) || 0);
  const pb = b.split(".").map((n) => parseInt(n, 10) || 0);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}
