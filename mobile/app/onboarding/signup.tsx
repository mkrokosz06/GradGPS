import React, { useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, KeyboardAvoidingView, Platform, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useAuth } from "../../context/AuthContext";
import { createUser } from "../../services/userService";

function StepDots({ step }: { step: number }) {
  return (
    <View style={{ flexDirection: "row", gap: 6, justifyContent: "center", marginBottom: 36 }}>
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

export default function SignupScreen() {
  const router = useRouter();
  const { signIn } = useAuth();

  const [name,    setName]    = useState("");
  const [email,   setEmail]   = useState("");
  const [loading, setLoading] = useState(false);

  async function handleContinue() {
    if (!name.trim())  { Alert.alert("Required", "Please enter your name."); return; }
    if (!email.trim()) { Alert.alert("Required", "Please enter your email."); return; }
    if (!email.includes("@")) { Alert.alert("Invalid", "Please enter a valid email address."); return; }

    setLoading(true);
    try {
      const user = await createUser(name.trim(), email.trim().toLowerCase());
      await signIn(user.user_id, user.name, user.email);
      router.push("/onboarding/major" as any);
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "Could not create account. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={styles.container}>
          <StepDots step={0} />

          <Text style={styles.heading}>Let's get started</Text>
          <Text style={styles.sub}>Create your GradGPS account.</Text>

          <View style={styles.fields}>
            <View style={styles.fieldGroup}>
              <Text style={styles.label}>Full name</Text>
              <TextInput
                style={styles.input}
                placeholder="Jane Smith"
                placeholderTextColor="#cbd5e1"
                value={name}
                onChangeText={setName}
                autoCapitalize="words"
                returnKeyType="next"
              />
            </View>

            <View style={styles.fieldGroup}>
              <Text style={styles.label}>Penn State email</Text>
              <TextInput
                style={styles.input}
                placeholder="abc1234@psu.edu"
                placeholderTextColor="#cbd5e1"
                value={email}
                onChangeText={setEmail}
                keyboardType="email-address"
                autoCapitalize="none"
                returnKeyType="done"
                onSubmitEditing={handleContinue}
              />
            </View>
          </View>

          <TouchableOpacity
            style={[styles.primaryBtn, loading && { opacity: 0.6 }]}
            onPress={handleContinue}
            disabled={loading}
            activeOpacity={0.85}
          >
            {loading
              ? <ActivityIndicator color="#ffffff" />
              : <Text style={styles.primaryBtnText}>Continue</Text>}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:        { flex: 1, backgroundColor: "#ffffff" },
  container:   { flex: 1, paddingHorizontal: 28, paddingTop: 48, paddingBottom: 32 },
  heading:     { fontSize: 30, fontWeight: "800", color: "#0f172a", marginBottom: 6 },
  sub:         { fontSize: 15, color: "#94a3b8", marginBottom: 36 },
  fields:      { gap: 20, marginBottom: 36 },
  fieldGroup:  { gap: 6 },
  label:       { fontSize: 12, fontWeight: "700", color: "#64748b", letterSpacing: 0.5 },
  input:       {
    borderWidth: 1.5, borderColor: "#e2e8f0", borderRadius: 14,
    paddingHorizontal: 16, paddingVertical: 14,
    fontSize: 15, color: "#0f172a", backgroundColor: "#f8fafc",
  },
  primaryBtn:  {
    backgroundColor: "#1a3a6b", borderRadius: 16,
    paddingVertical: 17, alignItems: "center",
  },
  primaryBtnText: { color: "#ffffff", fontSize: 16, fontWeight: "700" },
});
