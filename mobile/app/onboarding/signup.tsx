import React, { useEffect, useState } from "react";
import {
  View, Text, TouchableOpacity,
  StyleSheet, Platform, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as Google from "expo-auth-session/providers/google";
import * as AppleAuthentication from "expo-apple-authentication";
import * as WebBrowser from "expo-web-browser";
import { useAuth } from "../../context/AuthContext";
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

  const [googleLoading, setGoogleLoading] = useState(false);
  const [appleLoading,  setAppleLoading]  = useState(false);
  const [appleAvailable, setAppleAvailable] = useState(false);
  const [showTos, setShowTos] = useState(false);

  // Sign in with Apple is iOS-only and needs the native module present.
  useEffect(() => {
    if (Platform.OS === "ios") {
      AppleAuthentication.isAvailableAsync().then(setAppleAvailable).catch(() => setAppleAvailable(false));
    }
  }, []);

  // Google Sign-In (expo-auth-session). Yields an OIDC ID token the backend
  // verifies. Works on web + native builds; Expo Go cannot complete this flow.
  const [request, response, promptAsync] = Google.useIdTokenAuthRequest({
    webClientId: GOOGLE_WEB_CLIENT_ID || undefined,
    iosClientId: GOOGLE_IOS_CLIENT_ID || undefined,
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
          Alert.alert("Error", e?.response?.data?.detail ?? "Sign-in failed. Please try again.");
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

  // Apple returns the user's name ONLY on the first authorization, in the
  // credential (never inside the token). We forward it to the profile upsert
  // so the account isn't nameless; subsequent sign-ins reuse the stored name.
  async function handleApple() {
    setAppleLoading(true);
    try {
      const cred = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      const idToken = cred.identityToken;
      if (!idToken) {
        Alert.alert("Error", "Apple did not return an identity token.");
        return;
      }
      const name = cred.fullName
        ? [cred.fullName.givenName, cred.fullName.familyName].filter(Boolean).join(" ").trim()
        : "";
      await signInWithIdToken(idToken, {
        name:  name || undefined,
        email: cred.email || undefined,
      });
      setShowTos(true);
    } catch (e: any) {
      if (e?.code === "ERR_REQUEST_CANCELED") return; // user backed out
      Alert.alert("Error", e?.response?.data?.detail ?? "Apple sign-in failed. Please try again.");
    } finally {
      setAppleLoading(false);
    }
  }

  // Dev-only bypass so Expo Go / `expo start` can sign in as the seeded test
  // user — Google and Apple cannot complete in Expo Go. Stripped from
  // production/TestFlight builds by the __DEV__ guard.
  async function handleDevSignIn() {
    await signIn("matthew-test-001", "Matthew Krokosz", "matthew@psu.edu");
    setShowTos(true);
  }

  async function handleDeclineTos() {
    setShowTos(false);
    await signOut();
  }

  function handleAgreeTos() {
    setShowTos(false);
    router.push("/onboarding/major" as any);
  }

  const busy = googleLoading || appleLoading;

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <StepDots step={0} />

        <Text style={styles.heading}>Let's get started</Text>
        <Text style={styles.sub}>Sign in to create your GradGPS account.</Text>

        <View style={styles.buttons}>
          {appleAvailable && (
            <AppleAuthentication.AppleAuthenticationButton
              buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
              buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.BLACK}
              cornerRadius={16}
              style={styles.appleBtn}
              onPress={handleApple}
            />
          )}

          {GOOGLE_CONFIGURED && (
            <TouchableOpacity
              style={[styles.googleBtn, (busy || !request) && { opacity: 0.6 }]}
              onPress={handleGoogle}
              disabled={busy || !request}
              activeOpacity={0.85}
            >
              {googleLoading
                ? <ActivityIndicator color="#0f172a" />
                : <Text style={styles.googleBtnText}>Continue with Google</Text>}
            </TouchableOpacity>
          )}

          {__DEV__ && (
            <TouchableOpacity
              style={styles.devBtn}
              onPress={handleDevSignIn}
              activeOpacity={0.85}
            >
              <Text style={styles.devBtnText}>Dev sign-in (test user)</Text>
            </TouchableOpacity>
          )}
        </View>

        <Text style={styles.legal}>
          By continuing you agree to our Terms of Service and Privacy Policy.
        </Text>
      </View>
      <TosModal visible={showTos} onAgree={handleAgreeTos} onDecline={handleDeclineTos} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:      { flex: 1, backgroundColor: "#ffffff" },
  container: { flex: 1, paddingHorizontal: 28, paddingTop: 48, paddingBottom: 32 },
  heading:   { fontSize: 30, fontWeight: "800", color: "#0f172a", marginBottom: 6 },
  sub:       { fontSize: 15, color: "#94a3b8", marginBottom: 40 },
  buttons:   { gap: 16 },
  appleBtn:  { height: 54 },
  googleBtn: {
    borderWidth: 1.5, borderColor: "#e2e8f0", borderRadius: 16,
    paddingVertical: 16, alignItems: "center", backgroundColor: "#ffffff",
    height: 54, justifyContent: "center",
  },
  googleBtnText: { color: "#0f172a", fontSize: 16, fontWeight: "700" },
  devBtn: {
    borderWidth: 1.5, borderColor: "#fed7aa", borderRadius: 16,
    paddingVertical: 14, alignItems: "center", backgroundColor: "#fff7ed",
  },
  devBtnText: { color: "#c2410c", fontSize: 14, fontWeight: "700" },
  legal: {
    marginTop: "auto", fontSize: 12, color: "#cbd5e1",
    textAlign: "center", lineHeight: 18,
  },
});
