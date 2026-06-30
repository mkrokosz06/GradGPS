import React from "react";
import { View, Text, TouchableOpacity, Image, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

export default function WelcomeScreen() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.container}>
      {/* Logo */}
      <View style={styles.logoArea}>
        <Image
          source={require("../../assets/icon.png")}
          style={styles.logo}
          resizeMode="contain"
        />
        <Text style={styles.appName}>GradGPS</Text>
        <Text style={styles.tagline}>Navigate your degree.</Text>
      </View>

      {/* Bottom CTA */}
      <View style={styles.bottom}>
        <TouchableOpacity
          style={styles.primaryBtn}
          activeOpacity={0.85}
          onPress={() => router.push("/onboarding/signup" as any)}
        >
          <Text style={styles.primaryBtnText}>Get Started</Text>
        </TouchableOpacity>
        <Text style={styles.legalNote}>
          Free during beta.
        </Text>
        <View style={styles.legalLinks}>
          <TouchableOpacity onPress={() => router.push("/tos" as any)}>
            <Text style={styles.legalLink}>Terms of Service</Text>
          </TouchableOpacity>
          <Text style={styles.legalDot}>·</Text>
          <TouchableOpacity onPress={() => router.push("/privacy" as any)}>
            <Text style={styles.legalLink}>Privacy Policy</Text>
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#ffffff",
    justifyContent: "space-between",
    paddingHorizontal: 32,
    paddingBottom: 40,
  },
  logoArea: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
  },
  logo: {
    width: 120,
    height: 120,
    borderRadius: 26,
    marginBottom: 8,
  },
  appName: {
    fontSize: 38,
    fontWeight: "800",
    color: "#1a3a6b",
    letterSpacing: -0.5,
  },
  tagline: {
    fontSize: 17,
    color: "#94a3b8",
    fontWeight: "400",
  },
  bottom: {
    gap: 14,
    alignItems: "center",
  },
  primaryBtn: {
    width: "100%",
    backgroundColor: "#1a3a6b",
    paddingVertical: 17,
    borderRadius: 16,
    alignItems: "center",
  },
  primaryBtnText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
  },
  legalNote: {
    color: "#cbd5e1",
    fontSize: 12,
  },
  legalLinks: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  legalLink: {
    color: "#94a3b8",
    fontSize: 12,
    textDecorationLine: "underline",
  },
  legalDot: {
    color: "#cbd5e1",
    fontSize: 12,
  },
});
