import React, { createContext, useContext, useState, useEffect } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { setAuthToken } from "../services/api";
import { getStoredToken, storeToken, clearToken } from "../services/tokenStorage";
import { upsertMe } from "../services/userService";

type AuthState = {
  userId:             string | null;
  name:               string | null;
  email:              string | null;
  onboardingDone:     boolean;
  loading:            boolean;
  /** Legacy dev sign-in (x-user-id model). Works only against AUTH_DEV_BYPASS backends. */
  signIn:             (userId: string, name: string, email: string) => Promise<void>;
  /** Real sign-in: exchange a verified Google/Apple ID token for a session. */
  signInWithIdToken:  (idToken: string) => Promise<void>;
  completeOnboarding: () => Promise<void>;
  signOut:            () => Promise<void>;
};

const AuthContext = createContext<AuthState>({
  userId: null, name: null, email: null, onboardingDone: false, loading: true,
  signIn: async () => {}, signInWithIdToken: async () => {},
  completeOnboarding: async () => {}, signOut: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [userId,         setUserId]         = useState<string | null>(null);
  const [name,           setName]           = useState<string | null>(null);
  const [email,          setEmail]          = useState<string | null>(null);
  const [onboardingDone, setOnboardingDone] = useState(false);
  const [loading,        setLoading]        = useState(true);

  useEffect(() => {
    (async () => {
      try {
        // Restore a stored ID token first so the api interceptor is armed
        // before any authenticated calls fire.
        const token = await getStoredToken();
        if (token) setAuthToken(token);

        const pairs = await AsyncStorage.multiGet([
          "user_id", "user_name", "user_email", "onboarding_done",
        ]);
        const map = Object.fromEntries(pairs.map(([k, v]) => [k, v]));
        setUserId(map["user_id"] ?? null);
        setName(map["user_name"] ?? null);
        setEmail(map["user_email"] ?? null);
        setOnboardingDone(map["onboarding_done"] === "1");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  /** Legacy dev sign-in — kept until every environment runs real OAuth. */
  async function signIn(uid: string, n: string, e: string) {
    await AsyncStorage.multiSet([["user_id", uid], ["user_name", n], ["user_email", e]]);
    setUserId(uid); setName(n); setEmail(e);
  }

  /**
   * Real sign-in. Stores the ID token (SecureStore on native), arms the
   * Bearer interceptor, then upserts the profile — the backend answers with
   * the canonical provider-scoped user_id (e.g. "google:1234...").
   *
   * Note: Google ID tokens expire after ~1 hour; the backend will start
   * returning 401 after that and the user must sign in again. A proper
   * session/refresh mechanism is a follow-up.
   */
  async function signInWithIdToken(idToken: string) {
    await storeToken(idToken);
    setAuthToken(idToken);
    try {
      const user = await upsertMe();
      await AsyncStorage.multiSet([
        ["user_id", user.user_id],
        ["user_name", user.name ?? ""],
        ["user_email", user.email ?? ""],
      ]);
      setUserId(user.user_id); setName(user.name ?? null); setEmail(user.email ?? null);
    } catch (e) {
      // Roll back a half-completed sign-in so we don't strand a bad token.
      await clearToken();
      setAuthToken(null);
      throw e;
    }
  }

  async function completeOnboarding() {
    await AsyncStorage.setItem("onboarding_done", "1");
    setOnboardingDone(true);
  }

  async function signOut() {
    await clearToken();
    setAuthToken(null);
    await AsyncStorage.multiRemove(["user_id", "user_name", "user_email", "onboarding_done"]);
    setUserId(null); setName(null); setEmail(null); setOnboardingDone(false);
  }

  return (
    <AuthContext.Provider value={{
      userId, name, email, onboardingDone, loading,
      signIn, signInWithIdToken, completeOnboarding, signOut,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
