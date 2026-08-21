import { useEffect, useState } from "react";
import { View, Text, Pressable, Linking, Platform } from "react-native";
import * as Application from "expo-application";
import { fetchAppConfig, cmpVersions, AppConfig } from "../services/configService";

// Where "Update" sends the user when the backend doesn't specify a URL.
// itms-beta:// opens the TestFlight app directly on a device that has it.
const TESTFLIGHT_FALLBACK = "itms-beta://";

// Native marketing version of the running build (CFBundleShortVersionString on
// iOS). Null on Expo web and unavailable outside a real build — in that case we
// never gate (see UpdateGate below), so a missing value can't accidentally block.
const CURRENT_VERSION = Application.nativeApplicationVersion;

function openUpdate(url: string) {
  const target = url || TESTFLIGHT_FALLBACK;
  Linking.openURL(target).catch(() => {
    // If the specific target can't open (e.g. TestFlight not installed), try the
    // App Store product page as a last resort — harmless no-op if it also fails.
    Linking.openURL("https://apps.apple.com/app/gradgps/id0").catch(() => {});
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

/** Dismissible banner pinned to the bottom for an optional update. */
function UpdateBanner({ url, onDismiss }: { url: string; onDismiss: () => void }) {
  return (
    <View
      style={{
        position: "absolute",
        left: 12,
        right: 12,
        bottom: 24,
        backgroundColor: "#1a3a6b",
        borderRadius: 12,
        padding: 14,
        flexDirection: "row",
        alignItems: "center",
        shadowColor: "#000",
        shadowOpacity: 0.2,
        shadowRadius: 8,
        shadowOffset: { width: 0, height: 2 },
        elevation: 4,
      }}
    >
      <Text style={{ color: "#ffffff", flex: 1, fontSize: 14 }}>
        A new version of GradGPS is available.
      </Text>
      <Pressable onPress={() => openUpdate(url)} style={{ paddingHorizontal: 10, paddingVertical: 6 }}>
        <Text style={{ color: "#ffffff", fontWeight: "700", fontSize: 14 }}>Update</Text>
      </Pressable>
      <Pressable onPress={onDismiss} hitSlop={8} style={{ paddingHorizontal: 6, paddingVertical: 6 }}>
        <Text style={{ color: "#dbe4f3", fontSize: 18 }}>×</Text>
      </Pressable>
    </View>
  );
}

/**
 * Wraps the app and enforces the backend version gate:
 *  - current < min_supported  → hard block (BlockingUpdateScreen)
 *  - current < latest         → dismissible banner
 * Never gates when the native version is unavailable (Expo web / dev) or the
 * config fetch fails — the gate fails open so a backend hiccup can't lock users out.
 */
export function UpdateGate({ children }: { children: React.ReactNode }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [dismissed, setDismissed] = useState(false);

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

  if (cfg && canGate) {
    const url = cfg.ios_update_url;
    if (cmpVersions(CURRENT_VERSION!, cfg.min_supported_version) < 0) {
      return <BlockingUpdateScreen url={url} />;
    }
    if (!dismissed && cmpVersions(CURRENT_VERSION!, cfg.latest_version) < 0) {
      return (
        <>
          {children}
          <UpdateBanner url={url} onDismiss={() => setDismissed(true)} />
        </>
      );
    }
  }

  return <>{children}</>;
}
