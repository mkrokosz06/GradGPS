import React, { createContext, useContext, useState, useEffect } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { setAuthToken, setOnUnauthorized } from "../services/api";
import { getStoredToken, storeToken, clearToken } from "../services/tokenStorage";
import { upsertMe } from "../services/userService";
import { createSession, revokeSession } from "../services/authService";

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

  // Backend says the session is gone (revoked/expired past the 30-day window):
  // clear local state so RootRedirector routes back to sign-in.
  useEffect(() => {
    setOnUnauthorized(() => {
      clearToken();
      setAuthToken(null);
      AsyncStorage.multiRemove(["user_id", "user_name", "user_email", "onboarding_done"]);
      setUserId(null); setName(null); setEmail(null); setOnboardingDone(false);
    });
    return () => setOnUnauthorized(null);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        // Restore the stored session token first so the api interceptor is
        // armed before any authenticated calls fire.
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
   * Real sign-in. Exchanges the ~1 h Google/Apple ID token for a backend
   * session token (30-day sliding expiry), stores that (SecureStore on
   * native), arms the Bearer interceptor, then upserts the profile — the
   * backend answers with the canonical provider-scoped user_id.
   */
  async function signInWithIdToken(idToken: string) {
    const session = await createSession(idToken);
    await storeToken(session.session_token);
    setAuthToken(session.session_token);
    try {
      const user = await upsertMe();
      await AsyncStorage.multiSet([
        ["user_id", user.user_id],
        ["user_name", user.name ?? ""],
        ["user_email", user.email ?? ""],
      ]);
      setUserId(user.user_id); setName(user.name ?? null); setEmail(user.email ?? null);
    } catch (e) {
      // Roll back a half-completed sign-in so we don't strand a dead session.
      await revokeSession();
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
    await revokeSession(); // best-effort server-side revoke while the token is still armed
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
