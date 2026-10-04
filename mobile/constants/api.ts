import { Platform } from "react-native";
import Constants from "expo-constants";

// Dev (Expo Go / `expo start`): falls back to the laptop's LAN IP + local backend,
// which runs with AUTH_DEV_BYPASS. Production builds (`eas build`, `expo export`)
// load .env.production, where EXPO_PUBLIC_API_BASE points at the AWS backend —
// real Google auth only there (prod rejects x-user-id).
// The dev host is detected rather than hardcoded: a laptop's LAN IP changes with
// the network, and a stale one fails silently. Web: the page's own host. Native:
// the Metro host Expo Go / the dev client loaded the bundle from.
function devApiBase(): string {
  if (Platform.OS === "web" && typeof window !== "undefined") {
    return `http://${window.location.hostname}:8080`;
  }
  const host = Constants.expoConfig?.hostUri?.split(":")[0];
  return `http://${host ?? "localhost"}:8080`;
}

export const API_BASE = process.env.EXPO_PUBLIC_API_BASE ?? devApiBase();

// Google OAuth client IDs (from Google Cloud console → Credentials).
// Web client ID is used for Expo web; iOS client ID is used once the app
// runs as a dev build (Expo Go cannot do Google OAuth — no auth proxy).
// Leave empty until configured; the Google button hides itself when unset.
export const GOOGLE_WEB_CLIENT_ID = "1087629564900-sojfbjaopgi6cis3dlapr7hkm704iet4.apps.googleusercontent.com";
export const GOOGLE_IOS_CLIENT_ID = "1087629564900-60ve3eda3vrbcadgar8804dpu6fpjm7e.apps.googleusercontent.com";
