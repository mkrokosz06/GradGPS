import React, { useState, useRef } from "react";
import {
  View, Text, TouchableOpacity, Animated,
  Pressable, Modal, StyleSheet, Dimensions,
} from "react-native";
import { useRouter, usePathname } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

const MENU_WIDTH = Dimensions.get("window").width * 0.78;

const ALL_ITEMS = [
  { label: "Timeline",          route: "/",        match: ["/", "/index"] },
  { label: "Upload Transcript", route: "/upload",  match: ["/upload"] },
  { label: "Change Major",      route: "/major",   match: ["/major"] },
  { label: "Account",           route: "/account", match: ["/account"] },
];

export function NavHeader({ subtitle }: { subtitle?: string }) {
  const router   = useRouter();
  const pathname = usePathname();
  const insets   = useSafeAreaInsets();

  const [mounted, setMounted] = useState(false);
  const slideAnim = useRef(new Animated.Value(-MENU_WIDTH)).current;
  const fadeAnim  = useRef(new Animated.Value(0)).current;

  function openMenu() {
    setMounted(true);
    Animated.parallel([
      Animated.timing(slideAnim, { toValue: 0,           duration: 240, useNativeDriver: true }),
      Animated.timing(fadeAnim,  { toValue: 1,           duration: 240, useNativeDriver: true }),
    ]).start();
  }

  function closeMenu(after?: () => void) {
    Animated.parallel([
      Animated.timing(slideAnim, { toValue: -MENU_WIDTH, duration: 200, useNativeDriver: true }),
      Animated.timing(fadeAnim,  { toValue: 0,           duration: 200, useNativeDriver: true }),
    ]).start(() => {
      setMounted(false);
      after?.();
    });
  }

  function navigate(route: string) {
    closeMenu(() => router.navigate(route as any));
  }

  // Hide the current page from the menu
  const menuItems = ALL_ITEMS.filter((item) => !item.match.includes(pathname));

  return (
    <>
      {/* Top header bar */}
      <View style={styles.header}>
        <View style={{ flex: 1, marginRight: 12 }}>
          <Text style={styles.title}>GradGPS</Text>
          {subtitle ? (
            <Text style={styles.subtitle} numberOfLines={1}>{subtitle}</Text>
          ) : null}
        </View>
        <TouchableOpacity onPress={openMenu} activeOpacity={0.7} style={styles.menuBtn}>
          <Text style={styles.menuIcon}>≡</Text>
        </TouchableOpacity>
      </View>

      {/* Side menu */}
      {mounted && (
        <Modal transparent visible animationType="none" onRequestClose={() => closeMenu()}>
          <View style={{ flex: 1 }}>
            {/* Dimmed backdrop */}
            <Animated.View
              style={[StyleSheet.absoluteFillObject, { backgroundColor: "rgba(0,0,0,0.28)", opacity: fadeAnim }]}
            />
            <Pressable style={StyleSheet.absoluteFillObject} onPress={() => closeMenu()} />

            {/* Sliding panel */}
            <Animated.View style={[styles.panel, { transform: [{ translateX: slideAnim }] }]}>
              {/* Panel header */}
              <View style={[styles.panelHeader, { paddingTop: insets.top + 18 }]}>
                <Text style={styles.panelTitle}>GradGPS</Text>
                <TouchableOpacity onPress={() => closeMenu()} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                  <Text style={styles.closeBtn}>×</Text>
                </TouchableOpacity>
              </View>

              {/* Nav items (current page excluded) */}
              <View style={{ flex: 1, paddingTop: 6 }}>
                {menuItems.map((item) => (
                  <TouchableOpacity
                    key={item.route}
                    onPress={() => navigate(item.route)}
                    activeOpacity={0.55}
                    style={styles.menuItem}
                  >
                    <Text style={styles.menuLabel}>{item.label}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </Animated.View>
          </View>
        </Modal>
      )}
    </>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12,
    backgroundColor: "#ffffff",
    borderBottomWidth: 1, borderBottomColor: "#f1f5f9",
  },
  title:    { color: "#1a3a6b", fontSize: 20, fontWeight: "700" },
  subtitle: { color: "#94a3b8", fontSize: 11, marginTop: 2 },
  menuBtn:  {
    width: 38, height: 38, borderRadius: 10,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "#f1f5f9",
  },
  menuIcon: { color: "#1a3a6b", fontSize: 19, fontWeight: "700", lineHeight: 22 },

  panel: {
    position: "absolute", top: 0, bottom: 0, left: 0,
    width: MENU_WIDTH,
    backgroundColor: "#ffffff",
    shadowColor: "#000",
    shadowOffset: { width: 6, height: 0 },
    shadowOpacity: 0.1,
    shadowRadius: 18,
    elevation: 12,
  },
  panelHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 24, paddingBottom: 18,
    borderBottomWidth: 1, borderBottomColor: "#f1f5f9",
  },
  panelTitle: { color: "#1a3a6b", fontSize: 20, fontWeight: "700" },
  closeBtn:   { color: "#94a3b8", fontSize: 26, lineHeight: 28 },
  menuItem:   {
    paddingHorizontal: 24, paddingVertical: 17,
    borderBottomWidth: 1, borderBottomColor: "#f8fafc",
  },
  menuLabel:  { color: "#1e293b", fontSize: 16, fontWeight: "500" },
});
