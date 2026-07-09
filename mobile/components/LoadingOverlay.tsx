import React from "react";
import { View, Text, ActivityIndicator, Modal } from "react-native";

/**
 * Full-screen blocking overlay shown during async work (e.g. transcript upload).
 * Rendered as a Modal so it covers the screen in every state — including the
 * "replace transcript" flow where the underlying button has no spinner of its own.
 */
export function LoadingOverlay({
  visible,
  label = "Working…",
  sub = "This can take a few seconds",
}: {
  visible: boolean;
  label?: string;
  sub?: string;
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent>
      <View
        style={{
          flex: 1,
          backgroundColor: "rgba(15,23,42,0.55)",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <View
          style={{
            backgroundColor: "#ffffff",
            borderRadius: 20,
            paddingVertical: 28,
            paddingHorizontal: 40,
            alignItems: "center",
            minWidth: 220,
          }}
        >
          <ActivityIndicator size="large" color="#1a3a6b" />
          <Text style={{ color: "#1a3a6b", fontSize: 15, fontWeight: "700", marginTop: 16 }}>
            {label}
          </Text>
          {!!sub && (
            <Text style={{ color: "#94a3b8", fontSize: 12, marginTop: 4 }}>{sub}</Text>
          )}
        </View>
      </View>
    </Modal>
  );
}
