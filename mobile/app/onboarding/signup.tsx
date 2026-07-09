import React, { useEffect, useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, KeyboardAvoidingView, Platform, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";
import { useAuth } from "../../context/AuthContext";
import { createUser } from "../../services/userService";
import { GOOGLE_WEB_CLIENT_ID, GOOGLE_IOS_CLIENT_ID } from "../../constants/api";
import { TosModal } from "../../components/TosModal";

// Completes the pending auth session when the browser redirects back (web).
WebBrowser.maybeCompleteAuthSession();

// Google OAuth is configured when at least the platform-relevant client id exists.
const GOOGLE_CONFIGURED =
  Platform.OS === "web" ? !!GOOGLE_WEB_CLIENT_ID : !!GOOGLE_IOS_CLIENT_ID;

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
  const { signIn, signInWithIdToken, signOut } = useAuth();

  const [name,    setName]    = useState("");
  const [email,   setEmail]   = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [showTos, setShowTos] = useState(false);

  // Google Sign-In (expo-auth-session). Yields an OIDC ID token the backend
  // verifies. Works on web + dev builds; Expo Go cannot complete this flow.
  const [request, response, promptAsync] = Google.useIdTokenAuthRequest({
    webClientId: GOOGLE_WEB_CLIENT_ID || undefined,
    iosClientId: GOOGLE_IOS_CLIENT_ID || undefined,
    // Generic fallback so the hook doesn't throw on platforms whose client ID
    // isn't configured yet (e.g. iOS in Expo Go — the button is hidden there,
    // so this dummy value is never actually used to start a flow).
    clientId: GOOGLE_WEB_CLIENT_ID || "unconfigured.apps.googleusercontent.com",
  });

  useEffect(() => {
    if (!response) return;
    if (response.type === "success") {
      const idToken = (response.params as any)?.id_token;
      if (!idToken) {
        Alert.alert("Error", "Google did not return an ID token.");
        setGoogleLoading(false);
        return;
      }
      signInWithIdToken(idToken)
        .then(() => setShowTos(true))
        .catch((e: any) => {
          Alert.alert("Error", e?.response?.data?.detail ?? "Sign-in failed. Is the backend running?");
        })
        .finally(() => setGoogleLoading(false));
    } else if (response.type === "error") {
      Alert.alert("Error", "Google sign-in failed. Please try again.");
      setGoogleLoading(false);
    } else {
      setGoogleLoading(false); // dismissed / cancelled
    }
  }, [response]);

  function handleGoogle() {
    setGoogleLoading(true);
    promptAsync();
  }

  async function handleContinue() {
    if (!name.trim())  { Alert.alert("Required", "Please enter your name."); return; }
    if (!email.trim()) { Alert.alert("Required", "Please enter your email."); return; }
    if (!email.includes("@")) { Alert.alert("Invalid", "Please enter a valid email address."); return; }

    setLoading(true);
    try {
      const user = await createUser(name.trim(), email.trim().toLowerCase());
      await signIn(user.user_id, user.name, user.email);
      setShowTos(true);
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "Could not create account. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  async function handleDeclineTos() {
    setShowTos(false);
    await signOut();
  }

  function handleAgreeTos() {
    setShowTos(false);
    router.push("/onboarding/major" as any);
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

          {GOOGLE_CONFIGURED && (
            <>
              <TouchableOpacity
                style={[styles.googleBtn, (googleLoading || !request) && { opacity: 0.6 }]}
                onPress={handleGoogle}
                disabled={googleLoading || !request}
                activeOpacity={0.85}
              >
                {googleLoading
                  ? <ActivityIndicator color="#0f172a" />
                  : <Text style={styles.googleBtnText}>Continue with Google</Text>}
              </TouchableOpacity>

              <View style={styles.dividerRow}>
                <View style={styles.dividerLine} />
                <Text style={styles.dividerText}>or</Text>
                <View style={styles.dividerLine} />
              </View>
            </>
          )}

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
      <TosModal visible={showTos} onAgree={handleAgreeTos} onDecline={handleDeclineTos} />
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
  googleBtn: {
    borderWidth: 1.5, borderColor: "#e2e8f0", borderRadius: 16,
    paddingVertical: 16, alignItems: "center", backgroundColor: "#ffffff",
    marginBottom: 24,
  },
  googleBtnText: { color: "#0f172a", fontSize: 16, fontWeight: "700" },
  dividerRow:  { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 24 },
  dividerLine: { flex: 1, height: 1, backgroundColor: "#e2e8f0" },
  dividerText: { fontSize: 12, color: "#94a3b8", fontWeight: "600" },
});
