import React, { createContext, useContext, useState, useEffect } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { setAuthToken, setOnUnauthorized } from "../services/api";
import { getStoredToken, storeToken, clearToken } from "../services/tokenStorage";
import { upsertMe, getMe } from "../services/userService";
import { getTranscript } from "../services/transcriptService";
import { createSession, revokeSession } from "../services/authService";

/**
 * What the server already knows about a signing-in user, used to skip
 * onboarding steps they've already completed (their data lives on the server;
 * the local onboarding_done flag is wiped on sign-out).
 */
export type OnboardingStatus = { hasMajor: boolean; hasTranscript: boolean };

type AuthState = {
  userId:             string | null;
  name:               string | null;
  email:              string | null;
  onboardingDone:     boolean;
  loading:            boolean;
  /** Legacy dev sign-in (x-user-id model). Works only against AUTH_DEV_BYPASS backends. */
  signIn:             (userId: string, name: string, email: string) => Promise<void>;
  /**
   * Real sign-in: exchange a verified Google/Apple ID token for a session.
   * `profile` carries name/email the token itself omits — Apple only hands
   * over the user's name once, at first authorization, client-side.
   * Resolves with the server-known onboarding status so the caller can route a
   * returning user past steps they've already finished.
   */
  signInWithIdToken:  (idToken: string, profile?: { name?: string; email?: string }) => Promise<OnboardingStatus>;
  /** Adopt a server-minted session token directly (email/OTP sign-in already returns one). */
  signInWithSession:  (sessionToken: string, profile?: { name?: string; email?: string }) => Promise<OnboardingStatus>;
  completeOnboarding: () => Promise<void>;
  signOut:            () => Promise<void>;
};

const AuthContext = createContext<AuthState>({
  userId: null, name: null, email: null, onboardingDone: false, loading: true,
  signIn: async () => {},
  signInWithIdToken: async () => ({ hasMajor: false, hasTranscript: false }),
  signInWithSession: async () => ({ hasMajor: false, hasTranscript: false }),
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
  async function signInWithIdToken(idToken: string, profile?: { name?: string; email?: string }) {
    const session = await createSession(idToken);
    return signInWithSession(session.session_token, profile);
  }

  /**
   * Adopt a server-issued session token: store it, arm the Bearer interceptor,
   * then upsert the profile — the backend answers with the canonical user_id.
   * Shared by the OIDC path (after the ID-token exchange) and email/OTP
   * sign-in (which returns a session token straight from /auth/email/verify).
   *
   * Also rehydrates onboarding progress from the server: a returning user's
   * major/transcript live in DynamoDB, so we mark onboarding done locally when
   * both are present and hand the status back so the caller can route them
   * straight to Home instead of re-running the whole onboarding flow.
   */
  async function signInWithSession(sessionToken: string, profile?: { name?: string; email?: string }): Promise<OnboardingStatus> {
    await storeToken(sessionToken);
    setAuthToken(sessionToken);
    try {
      const user = await upsertMe(profile?.name, profile?.email);
      await AsyncStorage.multiSet([
        ["user_id", user.user_id],
        ["user_name", user.name ?? ""],
        ["user_email", user.email ?? ""],
      ]);
      setUserId(user.user_id); setName(user.name ?? null); setEmail(user.email ?? null);

      const status = await resolveOnboarding(user.user_id);
      if (status.hasMajor && status.hasTranscript) {
        await AsyncStorage.setItem("onboarding_done", "1");
        setOnboardingDone(true);
      }
      return status;
    } catch (e) {
      // Roll back a half-completed sign-in so we don't strand a dead session.
      await revokeSession();
      await clearToken();
      setAuthToken(null);
      throw e;
    }
  }

  /**
   * Ask the server what the caller has already completed. A missing profile
   * (404 for a brand-new account) or a transient read error degrades to
   * "not onboarded" — worst case the user just re-runs a step, never a crash.
   */
  async function resolveOnboarding(uid: string): Promise<OnboardingStatus> {
    let hasMajor = false;
    let hasTranscript = false;
    try {
      const me = await getMe();
      hasMajor = !!me.major;
    } catch {
      // brand-new profile / transient error → treat as not yet onboarded
    }
    try {
      const t = await getTranscript(uid);
      hasTranscript = t.has_transcript;
    } catch {
      // no transcript yet (or read failed) → onboarding resumes at upload
    }
    return { hasMajor, hasTranscript };
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
      signIn, signInWithIdToken, signInWithSession, completeOnboarding, signOut,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
