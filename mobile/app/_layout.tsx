import { Stack, useRouter, usePathname } from "expo-router";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { View, ActivityIndicator } from "react-native";
import { useEffect } from "react";
import "../global.css";
import { AuthProvider, useAuth } from "../context/AuthContext";

function RootRedirector() {
  const { userId, onboardingDone, loading } = useAuth();
  const router   = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (loading) return;
    const inOnboarding = pathname.startsWith("/onboarding");
    const isPublicLegal = pathname === "/tos" || pathname === "/privacy";
    if (!userId && !inOnboarding && !isPublicLegal) {
      router.replace("/onboarding" as any);
    } else if (userId && onboardingDone && inOnboarding) {
      router.replace("/" as any);
    }
  }, [userId, onboardingDone, loading, pathname]);

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: "#ffffff", alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color="#1a3a6b" size="large" />
      </View>
    );
  }

  return <Stack screenOptions={{ headerShown: false }} />;
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <View style={{ flex: 1, backgroundColor: "#ffffff" }}>
          <RootRedirector />
        </View>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
