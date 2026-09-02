// Dev (Expo Go / `expo start`): falls back to the laptop's LAN IP + local backend,
// which runs with AUTH_DEV_BYPASS. Production builds (`eas build`, `expo export`)
// load .env.production, where EXPO_PUBLIC_API_BASE points at the AWS backend —
// real Google auth only there (prod rejects x-user-id).
export const API_BASE =
  process.env.EXPO_PUBLIC_API_BASE ?? "http://104.39.251.236:8080";

// Google OAuth client IDs (from Google Cloud console → Credentials).
// Web client ID is used for Expo web; iOS client ID is used once the app
// runs as a dev build (Expo Go cannot do Google OAuth — no auth proxy).
// Leave empty until configured; the Google button hides itself when unset.
export const GOOGLE_WEB_CLIENT_ID = "1087629564900-sojfbjaopgi6cis3dlapr7hkm704iet4.apps.googleusercontent.com";
export const GOOGLE_IOS_CLIENT_ID = "1087629564900-60ve3eda3vrbcadgar8804dpu6fpjm7e.apps.googleusercontent.com";
