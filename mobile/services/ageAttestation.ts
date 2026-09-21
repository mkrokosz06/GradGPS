/**
 * Age-requirement attestation.
 *
 * The Terms of Use and Privacy Policy require users to be at least 13, and
 * to have a parent/guardian's agreement if under 18. GradGPS asks the user to
 * confirm that once, before they hand over any data.
 *
 * Deliberately client-only: it is stored in AsyncStorage (the same local-flag
 * pattern as `onboarding_done`) and never sent to the backend. Collecting or
 * storing a birthdate would mean holding another piece of personal information
 * about a minor, which makes the privacy position worse rather than better.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const AGE_KEY = "age_confirmed";

export async function isAgeConfirmed(): Promise<boolean> {
  try {
    return (await AsyncStorage.getItem(AGE_KEY)) === "1";
  } catch {
    return false; // unreadable storage → ask again rather than assume consent
  }
}

export async function setAgeConfirmed(): Promise<void> {
  try {
    await AsyncStorage.setItem(AGE_KEY, "1");
  } catch {
    // A failed write only means the user is asked once more next launch.
  }
}
