import React, { useEffect, useState } from "react";
import { View, Text, ScrollView, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "../../context/AuthContext";
import { NavHeader } from "../../components/NavHeader";
import { getAudit, type AuditSummary } from "../../services/auditService";

export default function AccountScreen() {
  const { userId, name, signOut } = useAuth();
  const [audit, setAudit] = useState<AuditSummary | null>(null);

  useEffect(() => {
    if (!userId) return;
    getAudit(userId).then(setAudit).catch(() => {});
  }, [userId]);

  const creditPct = audit ? Math.min(100, Math.round((audit.transcript_credits / 120) * 100)) : 0;

  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
      <NavHeader subtitle="Account" />
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ padding: 24, paddingBottom: 40 }}
        showsVerticalScrollIndicator={false}
      >
        {/* Avatar + name */}
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
          <Text style={{ color: "#1e293b", fontSize: 20, fontWeight: "700" }}>{name ?? "Student"}</Text>
          <Text style={{ color: "#94a3b8", fontSize: 13, marginTop: 3 }}>Penn State University</Text>
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
            <StatBox label="Credits Earned" value={audit.transcript_credits} sub="of 120" color="#1a3a6b" />
            <View style={{ width: 1, backgroundColor: "#f3f4f6" }} />
            <StatBox label="Progress"       value={`${creditPct}%`}          sub="complete"  color="#2a5298" />
            <View style={{ width: 1, backgroundColor: "#f3f4f6" }} />
            <StatBox label="Remaining"      value={120 - audit.transcript_credits} sub="credits" color="#94a3b8" />
          </View>
        )}

        {/* Degree slots */}
        {audit && (
          <View
            style={{
              borderRadius: 16, overflow: "hidden",
              borderWidth: 1, borderColor: "#e5e7eb",
              marginBottom: 28,
            }}
          >
            <SlotRow label="Requirements done"        value={audit.done}        color="#16a34a" />
            <SlotRow label="In progress"              value={audit.in_progress} color="#d97706" border />
            <SlotRow label="Still needed"             value={audit.missing}     color="#94a3b8" border />
          </View>
        )}

        {/* Sign out placeholder */}
        <TouchableOpacity
          activeOpacity={0.7}
          onPress={signOut}
          style={{
            borderRadius: 14, paddingVertical: 14,
            alignItems: "center",
            borderWidth: 1.5, borderColor: "#fca5a5",
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

function SlotRow({ label, value, color, border }: { label: string; value: number; color: string; border?: boolean }) {
  return (
    <View
      style={{
        flexDirection: "row", justifyContent: "space-between", alignItems: "center",
        paddingHorizontal: 18, paddingVertical: 14,
        borderTopWidth: border ? 1 : 0, borderTopColor: "#f3f4f6",
      }}
    >
      <Text style={{ color: "#64748b", fontSize: 13 }}>{label}</Text>
      <Text style={{ color, fontSize: 15, fontWeight: "700" }}>{value}</Text>
    </View>
  );
}
