import React, { useState, useCallback } from "react";
import { View, Text, ScrollView, TouchableOpacity, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { useAuth } from "../../context/AuthContext";
import { NavHeader } from "../../components/NavHeader";
import { getAudit, getCachedAudit, type AuditSummary } from "../../services/auditService";
import { deleteAccount } from "../../services/userService";
import { setCredentials, credentialErrorMessage } from "../../services/credentialService";
import { CredentialPickerModal } from "../../components/CredentialPickerModal";
import { CredentialRequirementModal } from "../../components/CredentialRequirementModal";

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
  const [deleting, setDeleting] = useState(false);

  // Declared minors / certificates. The audit is the source of truth (it carries
  // each credential's progress), so this screen never keeps a separate copy —
  // it re-reads after every change.
  const [pickerOpen, setPickerOpen]   = useState(false);
  const [savingCreds, setSavingCreds] = useState(false);
  // The adviser-defined requirement the student is confirming courses for.
  const [confirming, setConfirming] = useState<
    { program: string; group: string; text: string; threshold: number } | null
  >(null);

  /** The one adviser-defined requirement on a credential, if it still needs courses. */
  function openRequirement(c: any) {
    const g = (c.groups ?? []).find(
      (x: any) => x.group_type === "unstructured_credits",
    );
    if (!g) return;
    setConfirming({
      program: c.program,
      group: g.name,
      text: g.pool_text ?? "",
      threshold: g.threshold ?? 0,
    });
  }
  const credentials = audit?.credentials ?? [];

  async function saveCredentials(programs: string[]) {
    setSavingCreds(true);
    try {
      await setCredentials(userId!, programs);
      // Refetch rather than patching local state: declaring a credential changes
      // the audit (and the timeline on its next focus), and the server is the
      // authority on what it computed.
      if (userId) setAudit(await getAudit(userId));
    } catch (e) {
      Alert.alert("Error", credentialErrorMessage(e));
    } finally {
      setSavingCreds(false);
    }
  }

  async function addCredential(programName: string) {
    setPickerOpen(false);
    await saveCredentials([...credentials.map((c) => c.program), programName]);
  }

  function removeCredential(programName: string) {
    Alert.alert(
      "Remove this?",
      `${programName} will be removed from your plan, and its courses will leave your timeline.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: () =>
            saveCredentials(
              credentials.map((c) => c.program).filter((p) => p !== programName),
            ),
        },
      ],
    );
  }

  function confirmDeleteAccount() {
    Alert.alert(
      "Delete Account?",
      "This permanently deletes your account, your transcript, and all of your academic data. This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: handleDeleteAccount },
      ],
    );
  }

  async function handleDeleteAccount() {
    setDeleting(true);
    try {
      await deleteAccount();
      // Server already revoked every session; signOut just clears local state
      // (its own revoke call is best-effort and idempotent).
      await signOut();
    } catch {
      Alert.alert("Error", "Could not delete your account. Please check your connection and try again.");
    } finally {
      setDeleting(false);
    }
  }

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

        {/* Minors & certificates — declared here, never during onboarding */}
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
              MINORS & CERTIFICATES
            </Text>

            {credentials.length === 0 ? (
              <Text style={{ color: "#64748b", fontSize: 12, lineHeight: 17, marginBottom: 10 }}>
                Taking a minor or certificate? Add it and its remaining courses join your timeline.
              </Text>
            ) : (
              credentials.map((c) => (
                <View
                  key={c.program}
                  style={{
                    flexDirection: "row", alignItems: "center",
                    paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: "#e0e9ff",
                  }}
                >
                  <View style={{ flex: 1, marginRight: 10 }}>
                    <Text style={{ color: "#1a3a6b", fontSize: 13, fontWeight: "600", lineHeight: 18 }}>
                      {c.program}
                    </Text>
                    <Text style={{ color: "#2a5298", fontSize: 11, marginTop: 2 }}>
                      {c.done} of {c.done + c.in_progress + c.missing} requirements done
                    </Text>
                    {c.manual_credits ? (
                      <TouchableOpacity onPress={() => openRequirement(c)} style={{ marginTop: 4 }}>
                        <Text style={{ color: "#1a3a6b", fontSize: 11, fontWeight: "700" }}>
                          {(c.confirmed_credits ?? 0) >= c.manual_credits
                            ? `✓ ${c.manual_credits} cr confirmed with your adviser`
                            : `${c.confirmed_credits ?? 0} of ${c.manual_credits} cr chosen with your adviser ›`}
                        </Text>
                      </TouchableOpacity>
                    ) : null}
                  </View>
                  <TouchableOpacity
                    onPress={() => removeCredential(c.program)}
                    disabled={savingCreds}
                    hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                  >
                    <Text style={{ color: "#94a3b8", fontSize: 17 }}>×</Text>
                  </TouchableOpacity>
                </View>
              ))
            )}

            <TouchableOpacity
              onPress={() => setPickerOpen(true)}
              disabled={savingCreds}
              style={{ paddingTop: 12 }}
            >
              <Text style={{ color: "#1a3a6b", fontSize: 13, fontWeight: "700" }}>
                {savingCreds ? "Saving…" : "+ Add a minor or certificate"}
              </Text>
            </TouchableOpacity>
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

        {/* Delete account — deliberately low-key next to Sign Out */}
        <TouchableOpacity
          activeOpacity={0.7}
          onPress={confirmDeleteAccount}
          disabled={deleting}
          style={{ paddingVertical: 14, alignItems: "center", marginTop: 4 }}
        >
          <Text style={{ color: "#f87171", fontSize: 12, fontWeight: "600" }}>
            {deleting ? "Deleting Account…" : "Delete Account"}
          </Text>
        </TouchableOpacity>
      </ScrollView>

      <CredentialPickerModal
        visible={pickerOpen}
        alreadyDeclared={credentials.map((c) => c.program)}
        onPick={addCredential}
        onClose={() => setPickerOpen(false)}
      />

      <CredentialRequirementModal
        visible={!!confirming}
        program={confirming?.program ?? null}
        requirementGroup={confirming?.group ?? null}
        requirementText={confirming?.text}
        threshold={confirming?.threshold ?? 0}
        onSaved={async () => { if (userId) setAudit(await getAudit(userId)); }}
        onClose={() => setConfirming(null)}
      />
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
