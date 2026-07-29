import React, { useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, ScrollView,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "../../context/AuthContext";
import { NavHeader } from "../../components/NavHeader";
import { sendSupportMessage } from "../../services/supportService";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default function SupportScreen() {
  const { email: authEmail } = useAuth();

  const [email, setEmail]     = useState(authEmail ?? "");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent]       = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const canSend = EMAIL_RE.test(email.trim()) && message.trim().length >= 10 && !sending;

  async function submit() {
    if (!canSend) return;
    setSending(true);
    setError(null);
    try {
      await sendSupportMessage(email.trim(), subject.trim(), message.trim());
      setSent(true);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Couldn't send your message. Please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
      <NavHeader subtitle="Support" />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          className="flex-1"
          contentContainerStyle={{ padding: 24, paddingBottom: 40 }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {sent ? (
            <View className="items-center pt-16">
              <View
                style={{
                  width: 72, height: 72, borderRadius: 36,
                  backgroundColor: "#dcfce7",
                  alignItems: "center", justifyContent: "center",
                  marginBottom: 18,
                }}
              >
                <Text style={{ color: "#16a34a", fontSize: 34, fontWeight: "700" }}>✓</Text>
              </View>
              <Text style={{ color: "#1e293b", fontSize: 19, fontWeight: "700" }}>Message sent</Text>
              <Text style={{ color: "#64748b", fontSize: 14, marginTop: 8, textAlign: "center", lineHeight: 20 }}>
                Thanks for reaching out — we'll get back to you at{"\n"}
                <Text style={{ fontWeight: "600", color: "#1a3a6b" }}>{email.trim()}</Text>
              </Text>
              <TouchableOpacity
                activeOpacity={0.7}
                onPress={() => { setSent(false); setSubject(""); setMessage(""); }}
                style={{
                  marginTop: 28, borderRadius: 14,
                  paddingVertical: 12, paddingHorizontal: 24,
                  borderWidth: 1.5, borderColor: "#dbeafe",
                }}
              >
                <Text style={{ color: "#1a3a6b", fontSize: 14, fontWeight: "600" }}>Send another message</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <>
              <Text style={{ color: "#1e293b", fontSize: 20, fontWeight: "700", marginTop: 4 }}>
                Need a hand?
              </Text>
              <Text style={{ color: "#64748b", fontSize: 14, marginTop: 6, marginBottom: 22, lineHeight: 20 }}>
                Found a bug, a wrong requirement, or something confusing? Send us a note and
                we'll reply to your email.
              </Text>

              <Text style={styles.label}>YOUR EMAIL</Text>
              <TextInput
                value={email}
                onChangeText={setEmail}
                placeholder="you@psu.edu"
                placeholderTextColor="#cbd5e1"
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
                style={styles.input}
              />

              <Text style={styles.label}>SUBJECT (OPTIONAL)</Text>
              <TextInput
                value={subject}
                onChangeText={setSubject}
                placeholder="What's it about?"
                placeholderTextColor="#cbd5e1"
                maxLength={200}
                style={styles.input}
              />

              <Text style={styles.label}>MESSAGE</Text>
              <TextInput
                value={message}
                onChangeText={setMessage}
                placeholder="Tell us what's going on…"
                placeholderTextColor="#cbd5e1"
                multiline
                textAlignVertical="top"
                maxLength={5000}
                style={[styles.input, { height: 150, paddingTop: 14 }]}
              />

              {error && (
                <Text style={{ color: "#ef4444", fontSize: 13, marginBottom: 12 }}>{error}</Text>
              )}

              <TouchableOpacity
                activeOpacity={0.8}
                onPress={submit}
                disabled={!canSend}
                style={{
                  borderRadius: 14, paddingVertical: 15,
                  alignItems: "center", marginTop: 4,
                  backgroundColor: canSend ? "#1a3a6b" : "#cbd5e1",
                }}
              >
                {sending ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text style={{ color: "#ffffff", fontSize: 15, fontWeight: "700" }}>Send message</Text>
                )}
              </TouchableOpacity>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = {
  label: {
    color: "#94a3b8", fontSize: 11, fontWeight: "700" as const,
    letterSpacing: 0.8, marginBottom: 7,
  },
  input: {
    borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 14,
    paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 15, color: "#1e293b",
    marginBottom: 18, backgroundColor: "#fafbfc",
  },
};
