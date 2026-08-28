import React, { useEffect, useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, ScrollView,
  StyleSheet, KeyboardAvoidingView, Platform, ActivityIndicator, Alert, Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as Google from "expo-auth-session/providers/google";
import * as AppleAuthentication from "expo-apple-authentication";
import * as WebBrowser from "expo-web-browser";
import { useAuth } from "../../context/AuthContext";
import { startEmailAuth, verifyEmailCode } from "../../services/emailAuthService";
import { GOOGLE_WEB_CLIENT_ID, GOOGLE_IOS_CLIENT_ID } from "../../constants/api";
import { TosModal } from "../../components/TosModal";

// Completes the pending auth session when the browser redirects back (web).
WebBrowser.maybeCompleteAuthSession();

// Google OAuth is configured when at least the platform-relevant client id exists.
const GOOGLE_CONFIGURED =
  Platform.OS === "web" ? !!GOOGLE_WEB_CLIENT_ID : !!GOOGLE_IOS_CLIENT_ID;

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

export default function SignupScreen() {
  const router = useRouter();
  const { signIn, signInWithIdToken, signInWithSession, signOut } = useAuth();

  // Route a signed-in user by what the server already has on file, so returning
  // users aren't force-marched back through onboarding they already finished.
  function routeAfterSignIn(status: { hasMajor: boolean; hasTranscript: boolean }) {
    if (status.hasMajor && status.hasTranscript) {
      router.replace("/(tabs)/" as any);            // fully set up → Home
    } else if (status.hasMajor) {
      router.replace("/onboarding/upload" as any);  // resume at transcript upload
    } else {
      setShowTos(true);                             // brand-new account → agree, then pick a major
    }
  }

  const [googleLoading,  setGoogleLoading]  = useState(false);
  const [appleLoading,   setAppleLoading]   = useState(false);
  const [appleAvailable, setAppleAvailable] = useState(false);
  const [showTos, setShowTos] = useState(false);

  // Email / one-time-code sign-in
  const [name,  setName]  = useState("");
  const [email, setEmail] = useState("");
  const [code,  setCode]  = useState("");
  const [emailStep, setEmailStep] = useState<"form" | "code">("form");
  const [emailLoading,  setEmailLoading]  = useState(false);
  const [verifyLoading, setVerifyLoading] = useState(false);

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
        .then(routeAfterSignIn)
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
      const appleName = cred.fullName
        ? [cred.fullName.givenName, cred.fullName.familyName].filter(Boolean).join(" ").trim()
        : "";
      const status = await signInWithIdToken(idToken, {
        name:  appleName || undefined,
        email: cred.email || undefined,
      });
      routeAfterSignIn(status);
    } catch (e: any) {
      if (e?.code === "ERR_REQUEST_CANCELED") return; // user backed out
      Alert.alert("Error", e?.response?.data?.detail ?? "Apple sign-in failed. Please try again.");
    } finally {
      setAppleLoading(false);
    }
  }

  // Email / one-time-code: step 1 — request a code.
  async function handleStartEmail() {
    if (!name.trim())  { Alert.alert("Required", "Please enter your name."); return; }
    if (!email.includes("@")) { Alert.alert("Invalid", "Please enter a valid email address."); return; }
    setEmailLoading(true);
    try {
      await startEmailAuth(email.trim().toLowerCase());
      setCode("");
      setEmailStep("code");
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "Couldn't send a code. Please try again.");
    } finally {
      setEmailLoading(false);
    }
  }

  // Email / one-time-code: step 2 — verify the code and adopt the session.
  async function handleVerifyEmail() {
    if (!/^\d{6}$/.test(code.trim())) { Alert.alert("Invalid", "Enter the 6-digit code we emailed you."); return; }
    setVerifyLoading(true);
    try {
      const cleanEmail = email.trim().toLowerCase();
      const session = await verifyEmailCode(cleanEmail, code.trim(), name.trim() || undefined);
      const status = await signInWithSession(session.session_token, { name: name.trim() || undefined, email: cleanEmail });
      routeAfterSignIn(status);
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "That code didn't work. Please try again.");
    } finally {
      setVerifyLoading(false);
    }
  }

  async function handleResendCode() {
    try {
      await startEmailAuth(email.trim().toLowerCase());
      Alert.alert("Code sent", "We emailed you a new code.");
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "Couldn't resend the code.");
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

  const busy = googleLoading || appleLoading || emailLoading;

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <StepDots step={0} />
          <Text style={styles.heading}>Let's get started</Text>
          <Text style={styles.sub}>Sign in to create your GradGPS account.</Text>

          {emailStep === "form" ? (
            <>
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
                      : (
                        <View style={styles.googleBtnInner}>
                          <Image
                            source={require("../../assets/google-logo.png")}
                            style={styles.googleLogo}
                          />
                          <Text style={styles.googleBtnText}>Continue with Google</Text>
                        </View>
                      )}
                  </TouchableOpacity>
                )}
              </View>

              <View style={styles.dividerRow}>
                <View style={styles.dividerLine} />
                <Text style={styles.dividerText}>or continue with email</Text>
                <View style={styles.dividerLine} />
              </View>

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
                  <Text style={styles.label}>Email</Text>
                  <TextInput
                    style={styles.input}
                    placeholder="abc1234@psu.edu"
                    placeholderTextColor="#cbd5e1"
                    value={email}
                    onChangeText={setEmail}
                    keyboardType="email-address"
                    autoCapitalize="none"
                    returnKeyType="done"
                    onSubmitEditing={handleStartEmail}
                  />
                </View>
              </View>

              <TouchableOpacity
                style={[styles.primaryBtn, (busy) && { opacity: 0.6 }]}
                onPress={handleStartEmail}
                disabled={busy}
                activeOpacity={0.85}
              >
                {emailLoading
                  ? <ActivityIndicator color="#ffffff" />
                  : <Text style={styles.primaryBtnText}>Email me a sign-in code</Text>}
              </TouchableOpacity>

              {__DEV__ && (
                <TouchableOpacity style={styles.devBtn} onPress={handleDevSignIn} activeOpacity={0.85}>
                  <Text style={styles.devBtnText}>Dev sign-in (test user)</Text>
                </TouchableOpacity>
              )}
            </>
          ) : (
            <>
              <Text style={styles.codeIntro}>
                Enter the 6-digit code we sent to{"\n"}
                <Text style={{ fontWeight: "700", color: "#0f172a" }}>{email.trim().toLowerCase()}</Text>
              </Text>
              <TextInput
                style={styles.codeInput}
                placeholder="000000"
                placeholderTextColor="#cbd5e1"
                value={code}
                onChangeText={(t) => setCode(t.replace(/\D/g, "").slice(0, 6))}
                keyboardType="number-pad"
                maxLength={6}
                returnKeyType="done"
                autoFocus
                onSubmitEditing={handleVerifyEmail}
              />
              <TouchableOpacity
                style={[styles.primaryBtn, verifyLoading && { opacity: 0.6 }]}
                onPress={handleVerifyEmail}
                disabled={verifyLoading}
                activeOpacity={0.85}
              >
                {verifyLoading
                  ? <ActivityIndicator color="#ffffff" />
                  : <Text style={styles.primaryBtnText}>Verify &amp; continue</Text>}
              </TouchableOpacity>

              <View style={styles.codeActions}>
                <TouchableOpacity onPress={handleResendCode}>
                  <Text style={styles.linkText}>Resend code</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={() => setEmailStep("form")}>
                  <Text style={styles.linkText}>Use a different email</Text>
                </TouchableOpacity>
              </View>
            </>
          )}

          <Text style={styles.legal}>
            By continuing you agree to our Terms of Service and Privacy Policy.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
      <TosModal visible={showTos} onAgree={handleAgreeTos} onDecline={handleDeclineTos} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:      { flex: 1, backgroundColor: "#ffffff" },
  container: { flexGrow: 1, paddingHorizontal: 28, paddingTop: 48, paddingBottom: 32 },
  heading:   { fontSize: 30, fontWeight: "800", color: "#0f172a", marginBottom: 6 },
  sub:       { fontSize: 15, color: "#94a3b8", marginBottom: 32 },
  buttons:   { gap: 14 },
  appleBtn:  { height: 54 },
  googleBtn: {
    borderWidth: 1.5, borderColor: "#e2e8f0", borderRadius: 16,
    paddingVertical: 16, alignItems: "center", backgroundColor: "#ffffff",
    height: 54, justifyContent: "center",
  },
  googleBtnInner: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 12 },
  googleLogo: { width: 20, height: 20, resizeMode: "contain" },
  googleBtnText: { color: "#0f172a", fontSize: 16, fontWeight: "700" },
  dividerRow:  { flexDirection: "row", alignItems: "center", gap: 12, marginVertical: 24 },
  dividerLine: { flex: 1, height: 1, backgroundColor: "#e2e8f0" },
  dividerText: { fontSize: 12, color: "#94a3b8", fontWeight: "600" },
  fields:      { gap: 18, marginBottom: 24 },
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
  devBtn: {
    marginTop: 16, borderWidth: 1.5, borderColor: "#fed7aa", borderRadius: 16,
    paddingVertical: 14, alignItems: "center", backgroundColor: "#fff7ed",
  },
  devBtnText: { color: "#c2410c", fontSize: 14, fontWeight: "700" },
  codeIntro:  { fontSize: 15, color: "#64748b", marginBottom: 24, lineHeight: 22 },
  codeInput:  {
    borderWidth: 1.5, borderColor: "#e2e8f0", borderRadius: 14,
    paddingHorizontal: 16, paddingVertical: 16, marginBottom: 20,
    fontSize: 28, letterSpacing: 8, textAlign: "center",
    color: "#0f172a", backgroundColor: "#f8fafc", fontWeight: "700",
  },
  codeActions: { flexDirection: "row", justifyContent: "space-between", marginTop: 20 },
  linkText:    { fontSize: 14, color: "#1a3a6b", fontWeight: "700" },
  legal: {
    marginTop: "auto", paddingTop: 28, fontSize: 12, color: "#cbd5e1",
    textAlign: "center", lineHeight: 18,
  },
});
