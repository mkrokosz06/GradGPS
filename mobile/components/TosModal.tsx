import React, { useCallback, useState } from "react";
import { View, Text, TouchableOpacity, Modal, StyleSheet } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";

/**
 * Blocking "I agree to the Terms" modal shown right after account creation
 * (both email/password and Google sign-in flows), before onboarding continues.
 */
export function TosModal({
  visible,
  onAgree,
  onDecline,
}: {
  visible: boolean;
  onAgree: () => void;
  onDecline: () => void;
}) {
  const router = useRouter();

  // A native Modal renders above the whole navigator, so a pushed legal page
  // would load underneath it. Hide the modal while the user reads the page and
  // bring it back when this screen regains focus — the gate itself stays.
  const [viewingLegal, setViewingLegal] = useState(false);

  useFocusEffect(
    useCallback(() => {
      setViewingLegal(false);
    }, [])
  );

  function openLegal(path: string) {
    setViewingLegal(true);
    router.push(path as any);
  }

  return (
    <Modal visible={visible && !viewingLegal} transparent animationType="fade" statusBarTranslucent>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Text style={styles.title}>Before you continue</Text>
          <Text style={styles.body}>
            GradGPS is a student-built planning tool and is not official academic advising.
            By continuing, you agree to our{" "}
            <Text style={styles.link} onPress={() => openLegal("/tos")}>
              Terms of Service
            </Text>{" "}
            and{" "}
            <Text style={styles.link} onPress={() => openLegal("/privacy")}>
              Privacy Policy
            </Text>
            .
          </Text>

          <TouchableOpacity style={styles.primaryBtn} onPress={onAgree} activeOpacity={0.85}>
            <Text style={styles.primaryBtnText}>I Agree</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.declineBtn} onPress={onDecline} activeOpacity={0.7}>
            <Text style={styles.declineBtnText}>Decline</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 28,
  },
  card: {
    backgroundColor: "#ffffff",
    borderRadius: 20,
    paddingVertical: 28,
    paddingHorizontal: 24,
    width: "100%",
    maxWidth: 380,
  },
  title: { fontSize: 18, fontWeight: "800", color: "#0f172a", marginBottom: 12 },
  body: { fontSize: 14, lineHeight: 21, color: "#475569", marginBottom: 24 },
  link: { color: "#2a5298", fontWeight: "700", textDecorationLine: "underline" },
  primaryBtn: {
    backgroundColor: "#1a3a6b", borderRadius: 14,
    paddingVertical: 15, alignItems: "center", marginBottom: 10,
  },
  primaryBtnText: { color: "#ffffff", fontSize: 15, fontWeight: "700" },
  declineBtn: { paddingVertical: 8, alignItems: "center" },
  declineBtnText: { color: "#94a3b8", fontSize: 13, fontWeight: "600" },
});
