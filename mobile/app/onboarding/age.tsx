import React, { useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { setAgeConfirmed } from "../../services/ageAttestation";

/**
 * Age gate — the first step of onboarding, before sign-up collects anything.
 *
 * The policies state a 13+ minimum with parent/guardian consent under 18
 * (privacy "Age Requirement & Children's Privacy", terms "Who can use the
 * Service"), so the product has to actually ask. This is a self-attestation:
 * no birthdate is collected, nothing is sent to the backend, and the answer is
 * kept in AsyncStorage so it isn't re-asked on every launch.
 */
export default function AgeGateScreen() {
  const router = useRouter();
  const [blocked, setBlocked] = useState(false);

  async function handleConfirm() {
    await setAgeConfirmed();
    router.replace("/onboarding/signup" as any);
  }

  if (blocked) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.container}>
          <View style={styles.body}>
            <Text style={styles.heading}>GradGPS isn't available to you yet</Text>
            <Text style={styles.copy}>
              Thanks for stopping by. GradGPS is built for college students, and you have to be
              at least 13 years old to create an account, so we can't set one up for you right now.
              {"\n\n"}
              Come back when you're 13 — we'll be here.
            </Text>
          </View>

          <View style={styles.bottom}>
            <TouchableOpacity
              style={styles.secondaryBtn}
              activeOpacity={0.7}
              onPress={() => router.replace("/onboarding" as any)}
            >
              <Text style={styles.secondaryBtnText}>Go back</Text>
            </TouchableOpacity>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <View style={styles.body}>
          <Text style={styles.heading}>Before you get started</Text>
          <Text style={styles.copy}>
            GradGPS is built for current and prospective college students.
            {"\n\n"}
            You must be at least 13 years old to use GradGPS. If you are under 18, you may use it
            only with the consent of a parent or guardian, who accepts our{" "}
            <Text style={styles.link} onPress={() => router.push("/tos" as any)}>
              Terms of Use
            </Text>{" "}
            and{" "}
            <Text style={styles.link} onPress={() => router.push("/privacy" as any)}>
              Privacy Policy
            </Text>{" "}
            on your behalf.
          </Text>
        </View>

        <View style={styles.bottom}>
          <Text style={styles.attest}>
            By continuing, you confirm that you are at least 13 years old, and that if you are
            under 18 your parent or guardian agrees to these terms on your behalf.
          </Text>

          <TouchableOpacity style={styles.primaryBtn} activeOpacity={0.85} onPress={handleConfirm}>
            <Text style={styles.primaryBtnText}>I Confirm</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.secondaryBtn}
            activeOpacity={0.7}
            onPress={() => setBlocked(true)}
          >
            <Text style={styles.secondaryBtnText}>I'm under 13</Text>
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:      { flex: 1, backgroundColor: "#ffffff" },
  container: { flex: 1, paddingHorizontal: 32, paddingTop: 48, paddingBottom: 40, justifyContent: "space-between" },
  body:      { flex: 1, justifyContent: "center" },
  heading:   { fontSize: 28, fontWeight: "800", color: "#0f172a", marginBottom: 14, letterSpacing: -0.3 },
  copy:      { fontSize: 15, lineHeight: 23, color: "#475569" },
  link:      { color: "#2a5298", fontWeight: "700", textDecorationLine: "underline" },
  bottom:    { gap: 12 },
  attest:    { fontSize: 12, lineHeight: 18, color: "#94a3b8", textAlign: "center", marginBottom: 2 },
  primaryBtn: {
    width: "100%", backgroundColor: "#1a3a6b",
    paddingVertical: 17, borderRadius: 16, alignItems: "center",
  },
  primaryBtnText:   { color: "#ffffff", fontSize: 16, fontWeight: "700" },
  secondaryBtn:     { paddingVertical: 10, alignItems: "center" },
  secondaryBtnText: { color: "#94a3b8", fontSize: 13, fontWeight: "600" },
});
