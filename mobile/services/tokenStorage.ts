/**
 * ID-token storage.
 * Native: expo-secure-store (iOS Keychain / Android Keystore).
 * Web:    SecureStore is unavailable — falls back to AsyncStorage
 *         (localStorage), acceptable for the dev/testing web flow.
 */
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";

const TOKEN_KEY = "auth_id_token";

export async function getStoredToken(): Promise<string | null> {
  if (Platform.OS === "web") return AsyncStorage.getItem(TOKEN_KEY);
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function storeToken(token: string): Promise<void> {
  if (Platform.OS === "web") return AsyncStorage.setItem(TOKEN_KEY, token);
  return SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function clearToken(): Promise<void> {
  if (Platform.OS === "web") return AsyncStorage.removeItem(TOKEN_KEY);
  return SecureStore.deleteItemAsync(TOKEN_KEY);
}
