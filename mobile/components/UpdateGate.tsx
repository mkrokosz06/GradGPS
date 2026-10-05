import { useEffect, useState } from "react";
import { View, Text, Pressable, Linking, Platform, Alert } from "react-native";
import * as Application from "expo-application";
import { fetchAppConfig, cmpVersions, AppConfig } from "../services/configService";

// Where "Update" sends the user when the backend doesn't specify a URL.
// itms-apps:// opens GradGPS's page directly in the App Store app.
const APP_STORE_URL = "itms-apps://apps.apple.com/app/id6803643612";
const APP_STORE_WEB_URL = "https://apps.apple.com/app/id6803643612";

// Native marketing version of the running build (CFBundleShortVersionString on
// iOS). Null on Expo web and unavailable outside a real build — in that case we
// never gate (see UpdateGate below), so a missing value can't accidentally block.
const CURRENT_VERSION = Application.nativeApplicationVersion;

function openUpdate(url: string) {
  const target = url || APP_STORE_URL;
  Linking.openURL(target).catch(() => {
    // If the specific target can't open, try the App Store web page as a last
    // resort — harmless no-op if it also fails.
    Linking.openURL(APP_STORE_WEB_URL).catch(() => {});
  });
}

/** Full-screen, non-dismissible "you must update" wall. */
function BlockingUpdateScreen({ url }: { url: string }) {
  return (
    <View
      style={{
        flex: 1,
        backgroundColor: "#1a3a6b",
        alignItems: "center",
        justifyContent: "center",
        padding: 32,
      }}
    >
      <Text style={{ color: "#ffffff", fontSize: 24, fontWeight: "700", textAlign: "center" }}>
        Update required
      </Text>
      <Text
        style={{
          color: "#dbe4f3",
          fontSize: 16,
          textAlign: "center",
          marginTop: 16,
          lineHeight: 22,
        }}
      >
        This version of GradGPS is out of date and no longer supported. Please
        update to the latest version to continue.
      </Text>
      <Pressable
        onPress={() => openUpdate(url)}
        style={{
          backgroundColor: "#ffffff",
          paddingVertical: 14,
          paddingHorizontal: 40,
          borderRadius: 12,
          marginTop: 32,
        }}
      >
        <Text style={{ color: "#1a3a6b", fontSize: 16, fontWeight: "700" }}>Update now</Text>
      </Pressable>
    </View>
  );
}

/**
 * Wraps the app and enforces the backend version gate:
 *  - current < min_supported  → hard block (BlockingUpdateScreen)
 *  - current < latest         → "Update available" alert (Update / Later), once per launch
 * Never gates when the native version is unavailable (Expo web / dev) or the
 * config fetch fails — the gate fails open so a backend hiccup can't lock users out.
 */
export function UpdateGate({ children }: { children: React.ReactNode }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null);

  useEffect(() => {
    let alive = true;
    fetchAppConfig()
      .then((c) => alive && setCfg(c))
      .catch(() => {}); // fail open — no gate if config can't be reached
    return () => {
      alive = false;
    };
  }, []);

  // No native version to compare against (web/dev) → never gate.
  const canGate = Platform.OS !== "web" && !!CURRENT_VERSION;

  // An optional update asks once per launch, the way most apps do: "Later"
  // closes it until the app is next opened. A blocked version never gets here.
  useEffect(() => {
    if (!cfg || !canGate) return;
    if (cmpVersions(CURRENT_VERSION!, cfg.min_supported_version) < 0) return;
    if (cmpVersions(CURRENT_VERSION!, cfg.latest_version) >= 0) return;
    Alert.alert(
      "Update available",
      "A new version of GradGPS is available. Update now to get the latest features and fixes.",
      [
        { text: "Later", style: "cancel" },
        { text: "Update", onPress: () => openUpdate(cfg.ios_update_url) },
      ],
    );
  }, [cfg, canGate]);

  if (cfg && canGate) {
    const url = cfg.ios_update_url;
    if (cmpVersions(CURRENT_VERSION!, cfg.min_supported_version) < 0) {
      return <BlockingUpdateScreen url={url} />;
    }
  }

  return <>{children}</>;
}
