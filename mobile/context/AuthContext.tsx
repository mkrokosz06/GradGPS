import React, { createContext, useContext, useState, useEffect } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { USER_ID } from "../constants/api";

type AuthState = {
  userId:             string | null;
  name:               string | null;
  email:              string | null;
  onboardingDone:     boolean;
  loading:            boolean;
  signIn:             (userId: string, name: string, email: string) => Promise<void>;
  completeOnboarding: () => Promise<void>;
  signOut:            () => Promise<void>;
};

const AuthContext = createContext<AuthState>({
  userId: null, name: null, email: null, onboardingDone: false, loading: true,
  signIn: async () => {}, completeOnboarding: async () => {}, signOut: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [userId,         setUserId]         = useState<string | null>(null);
  const [name,           setName]           = useState<string | null>(null);
  const [email,          setEmail]          = useState<string | null>(null);
  const [onboardingDone, setOnboardingDone] = useState(false);
  const [loading,        setLoading]        = useState(true);

  useEffect(() => {
    AsyncStorage.multiGet(["user_id", "user_name", "user_email", "onboarding_done"]).then((pairs) => {
      const map = Object.fromEntries(pairs.map(([k, v]) => [k, v]));
      // Dev fallback: seed hardcoded test user so the app works without a sign-in flow.
      const resolvedId = map["user_id"] ?? USER_ID;
      setUserId(resolvedId);
      setName(map["user_name"]  ?? null);
      setEmail(map["user_email"] ?? null);
      // Mark onboarding done for the dev user so RootRedirector never
      // bounces to an onboarding screen that does not exist yet.
      setOnboardingDone(map["onboarding_done"] === "1" || resolvedId === USER_ID);
    }).finally(() => setLoading(false));
  }, []);

  async function signIn(uid: string, n: string, e: string) {
    await AsyncStorage.multiSet([["user_id", uid], ["user_name", n], ["user_email", e]]);
    setUserId(uid); setName(n); setEmail(e);
  }

  async function completeOnboarding() {
    await AsyncStorage.setItem("onboarding_done", "1");
    setOnboardingDone(true);
  }

  async function signOut() {
    await AsyncStorage.multiRemove(["user_id", "user_name", "user_email", "onboarding_done"]);
    setUserId(null); setName(null); setEmail(null); setOnboardingDone(false);
  }

  return (
    <AuthContext.Provider value={{ userId, name, email, onboardingDone, loading, signIn, completeOnboarding, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
