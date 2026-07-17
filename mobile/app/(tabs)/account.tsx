import React, { useState, useCallback } from "react";
import { View, Text, ScrollView, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { useAuth } from "../../context/AuthContext";
import { NavHeader } from "../../components/NavHeader";
import { getAudit, getCachedAudit, type AuditSummary } from "../../services/auditService";

function classYear(credits: number): string {
  if (credits < 30)  return "Freshman";
  if (credits < 60)  return "Sophomore";
  if (credits < 90)  return "Junior";
  return "Senior";
}

export default function AccountScreen() {
  const { userId, name, email, signOut } = useAuth();
  const [audit, setAudit] = useState<AuditSummary | null>(
    () => (userId ? getCachedAudit(userId) : null),
  );

  useFocusEffect(
    useCallback(() => {
      if (!userId) { setAudit(null); return; }
      // Show the last known audit immediately, then refresh in the background.
      setAudit(getCachedAudit(userId));
      getAudit(userId).then(setAudit).catch(() => {});
    }, [userId]),
  );

  const creditPct = audit ? Math.min(100, Math.round((audit.transcript_credits / 120) * 100)) : 0;
  const year      = audit ? classYear(audit.transcript_credits) : null;

  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
      <NavHeader subtitle="Account" />
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ padding: 24, paddingBottom: 40 }}
        showsVerticalScrollIndicator={false}
      >
        {/* Avatar + name + year */}
        <View className="items-center pt-4 pb-8">
          <View
            style={{
              width: 80, height: 80, borderRadius: 40,
              backgroundColor: "#1a3a6b",
              alignItems: "center", justifyContent: "center",
              marginBottom: 14,
            }}
          >
            <Text style={{ color: "#ffffff", fontSize: 30, fontWeight: "700" }}>
              {name ? name[0].toUpperCase() : "?"}
            </Text>
          </View>
          <Text style={{ color: "#1e293b", fontSize: 20, fontWeight: "700" }}>
            {name ? name.replace(/\b\w/g, (c) => c.toUpperCase()) : "Student"}
          </Text>
          {year && (
            <View style={{
              marginTop: 6, paddingHorizontal: 12, paddingVertical: 3,
              backgroundColor: "#dbeafe", borderRadius: 12,
            }}>
              <Text style={{ color: "#1a3a6b", fontSize: 12, fontWeight: "700" }}>{year}</Text>
            </View>
          )}
          {email && (
            <Text style={{ color: "#94a3b8", fontSize: 12, marginTop: 6 }}>{email}</Text>
          )}
          <Text style={{ color: "#cbd5e1", fontSize: 11, marginTop: 2 }}>Penn State University</Text>
        </View>

        {/* Major card */}
        {audit && (
          <View
            style={{
              backgroundColor: "#f0f4ff",
              borderRadius: 16, padding: 18,
              borderWidth: 1, borderColor: "#dbeafe",
              marginBottom: 16,
            }}
          >
            <Text style={{ color: "#94a3b8", fontSize: 11, fontWeight: "700", marginBottom: 5, letterSpacing: 0.8 }}>
              MAJOR
            </Text>
            <Text style={{ color: "#1a3a6b", fontSize: 13, fontWeight: "600", lineHeight: 18 }}>
              {audit.major}
            </Text>
            {audit.subplan ? (
              <Text style={{ color: "#2a5298", fontSize: 12, marginTop: 4 }}>{audit.subplan}</Text>
            ) : null}
          </View>
        )}

        {/* Credit progress bar */}
        {audit && (
          <View
            style={{
              borderRadius: 16, padding: 18,
              borderWidth: 1, borderColor: "#e5e7eb",
              marginBottom: 16,
            }}
          >
            <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 10 }}>
              <Text style={{ color: "#64748b", fontSize: 13, fontWeight: "600" }}>Credit Progress</Text>
              <Text style={{ color: "#1a3a6b", fontSize: 13, fontWeight: "700" }}>
                {audit.transcript_credits} / 120
              </Text>
            </View>
            <View style={{ height: 10, backgroundColor: "#f1f5f9", borderRadius: 5, overflow: "hidden" }}>
              <View style={{ height: "100%", width: `${creditPct}%`, backgroundColor: "#1a3a6b", borderRadius: 5 }} />
            </View>
            <Text style={{ color: "#94a3b8", fontSize: 11, marginTop: 8, textAlign: "right" }}>
              {120 - audit.transcript_credits} credits remaining
            </Text>
          </View>
        )}

        {/* Stats row */}
        {audit && (
          <View
            style={{
              flexDirection: "row",
              borderRadius: 16, overflow: "hidden",
              borderWidth: 1, borderColor: "#e5e7eb",
              marginBottom: 16,
            }}
          >
            <StatBox label="Done"        value={audit.done}        sub="requirements" color="#16a34a" />
            <View style={{ width: 1, backgroundColor: "#f3f4f6" }} />
            <StatBox label="In Progress" value={audit.in_progress} sub="requirements" color="#d97706" />
            <View style={{ width: 1, backgroundColor: "#f3f4f6" }} />
            <StatBox label="Remaining"   value={audit.missing}     sub="requirements" color="#94a3b8" />
          </View>
        )}

        {/* Sign out */}
        <TouchableOpacity
          activeOpacity={0.7}
          onPress={signOut}
          style={{
            borderRadius: 14, paddingVertical: 14,
            alignItems: "center",
            borderWidth: 1.5, borderColor: "#fca5a5",
            marginTop: 12,
          }}
        >
          <Text style={{ color: "#ef4444", fontSize: 14, fontWeight: "600" }}>Sign Out</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function StatBox({ label, value, sub, color }: { label: string; value: number | string; sub: string; color: string }) {
  return (
    <View style={{ flex: 1, alignItems: "center", paddingVertical: 18 }}>
      <Text style={{ color, fontSize: 22, fontWeight: "700" }}>{value}</Text>
      <Text style={{ color: "#94a3b8", fontSize: 10, marginTop: 2 }}>{sub}</Text>
      <Text style={{ color: "#cbd5e1", fontSize: 10, marginTop: 1 }}>{label}</Text>
    </View>
  );
}
