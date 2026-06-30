import React, { useState } from "react";
import {
  View, Text, TouchableOpacity,
  StyleSheet, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import { useAuth } from "../../context/AuthContext";
import { uploadTranscript } from "../../services/transcriptService";

function StepDots({ step }: { step: number }) {
  return (
    <View style={{ flexDirection: "row", gap: 6, justifyContent: "center", marginBottom: 32 }}>
      {[0, 1, 2].map((i) => (
        <View key={i} style={{
          height: 5, borderRadius: 3,
          width: i === step ? 22 : 6,
          backgroundColor: i <= step ? "#1a3a6b" : "#e2e8f0",
        }} />
      ))}
    </View>
  );
}

export default function OnboardingUploadScreen() {
  const router     = useRouter();
  const { userId, completeOnboarding } = useAuth();

  const [uploading, setUploading] = useState(false);
  const [done,      setDone]      = useState(false);
  const [parsed,    setParsed]    = useState(0);

  async function pickAndUpload() {
    const picked = await DocumentPicker.getDocumentAsync({
      type: "application/pdf",
      copyToCacheDirectory: true,
    });
    if (picked.canceled || !picked.assets?.length) return;

    const file = picked.assets[0];
    setUploading(true);

    try {
      const data = await uploadTranscript(userId!, file.uri, file.name ?? "transcript.pdf");
      setParsed(data.courses_parsed);
      setDone(true);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.response?.data?.detail ?? "Something went wrong.");
    } finally {
      setUploading(false);
    }
  }

  async function finish() {
    await completeOnboarding();
    router.replace("/(tabs)/" as any);
  }

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <StepDots step={2} />

        {done ? (
          /* ── Success state ── */
          <View style={{ flex: 1 }}>
            <Text style={styles.heading}>You're all set!</Text>
            <Text style={styles.sub}>
              {parsed} courses imported from your transcript.
            </Text>

            <View style={styles.successCard}>
              <View style={styles.checkCircle}>
                <Text style={{ color: "#16a34a", fontSize: 28, fontWeight: "700" }}>✓</Text>
              </View>
              <Text style={styles.successText}>Transcript uploaded</Text>
              <Text style={styles.successSub}>
                Your degree plan is ready.
              </Text>
            </View>

            <TouchableOpacity style={[styles.primaryBtn, { marginTop: "auto" }]} onPress={finish} activeOpacity={0.85}>
              <Text style={styles.primaryBtnText}>Go to Home</Text>
            </TouchableOpacity>
          </View>
        ) : (
          /* ── Upload state ── */
          <View style={{ flex: 1 }}>
            <Text style={styles.heading}>Upload your transcript</Text>
            <Text style={styles.sub}>
              We'll map your completed courses to your degree plan automatically.
            </Text>

            <View style={styles.instructionCard}>
              <Text style={styles.instructionTitle}>How to get your transcript</Text>
              <Text style={styles.instructionBody}>
                1. Log in to LionPATH{"\n"}
                2. Student Center → My Academics{"\n"}
                3. Download Unofficial Transcript as PDF
              </Text>
            </View>

            <TouchableOpacity
              onPress={pickAndUpload}
              disabled={uploading}
              activeOpacity={0.85}
              style={styles.uploadZone}
            >
              {uploading ? (
                <>
                  <ActivityIndicator color="#1a3a6b" size="large" />
                  <Text style={{ color: "#2a5298", fontSize: 14, fontWeight: "600", marginTop: 14 }}>
                    Parsing transcript…
                  </Text>
                </>
              ) : (
                <>
                  <View style={styles.uploadIcon}>
                    <Text style={{ color: "#ffffff", fontSize: 26, lineHeight: 30 }}>↑</Text>
                  </View>
                  <Text style={{ color: "#1a3a6b", fontSize: 15, fontWeight: "700", marginTop: 14 }}>
                    Tap to upload PDF
                  </Text>
                  <Text style={{ color: "#94a3b8", fontSize: 12, marginTop: 4 }}>
                    Unofficial PSU transcript
                  </Text>
                </>
              )}
            </TouchableOpacity>

            <TouchableOpacity onPress={finish} style={styles.skipBtn} activeOpacity={0.6}>
              <Text style={styles.skipText}>Skip for now</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:       { flex: 1, backgroundColor: "#ffffff" },
  container:  { flex: 1, paddingHorizontal: 24, paddingTop: 48, paddingBottom: 36 },
  heading:    { fontSize: 28, fontWeight: "800", color: "#0f172a", marginBottom: 6 },
  sub:        { fontSize: 14, color: "#94a3b8", marginBottom: 28 },

  instructionCard: {
    backgroundColor: "#f0f4ff", borderRadius: 16,
    padding: 18, borderWidth: 1, borderColor: "#dbeafe", marginBottom: 24,
  },
  instructionTitle: { color: "#1a3a6b", fontWeight: "700", fontSize: 13, marginBottom: 8 },
  instructionBody:  { color: "#475569", fontSize: 13, lineHeight: 22 },

  uploadZone: {
    borderWidth: 2, borderStyle: "dashed", borderColor: "#1a3a6b",
    borderRadius: 20, paddingVertical: 44, alignItems: "center",
    backgroundColor: "#f0f4ff", marginBottom: 20,
  },
  uploadIcon: {
    width: 52, height: 52, borderRadius: 14,
    backgroundColor: "#1a3a6b", alignItems: "center", justifyContent: "center",
  },

  skipBtn:  { alignItems: "center", paddingVertical: 10 },
  skipText: { color: "#94a3b8", fontSize: 14, fontWeight: "500" },

  successCard: {
    borderRadius: 20, borderWidth: 1, borderColor: "#e5e7eb",
    alignItems: "center", paddingVertical: 40, marginBottom: 28,
  },
  checkCircle: {
    width: 64, height: 64, borderRadius: 32,
    backgroundColor: "#f0fdf4", alignItems: "center", justifyContent: "center",
    marginBottom: 16,
  },
  successText: { color: "#0f172a", fontSize: 18, fontWeight: "700", marginBottom: 6 },
  successSub:  { color: "#94a3b8", fontSize: 13 },

  primaryBtn:     { backgroundColor: "#1a3a6b", borderRadius: 16, paddingVertical: 17, alignItems: "center" },
  primaryBtnText: { color: "#ffffff", fontSize: 16, fontWeight: "700" },
});
