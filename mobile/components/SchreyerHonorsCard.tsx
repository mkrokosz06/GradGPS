import React, { useEffect, useState } from "react";
import { View, Text, TouchableOpacity, ActivityIndicator, Alert } from "react-native";
import {
  getMyHonors, setMyHonors, SCHREYER_ENTRIES, type Honors, type SchreyerEntry,
} from "../services/honorsService";

/**
 * Account-page card: "I'm a Schreyer Scholar". Shown to every student, since
 * any major can have Scholars. Declaring swaps in the student's honors thesis
 * where their department lets it replace electives.
 */
export function SchreyerHonorsCard({
  userId, onChanged,
}: { userId: string; onChanged: () => void }) {
  const [honors, setHonors] = useState<Honors | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    getMyHonors(userId)
      .then((h) => { if (active) { setHonors(h); setLoaded(true); } })
      .catch(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, [userId]);

  if (!loaded) return null;
  const entryLabel = SCHREYER_ENTRIES.find((e) => e.value === honors?.entry)?.label;

  async function choose(entry: SchreyerEntry | null) {
    setSaving(true);
    try {
      setHonors(await setMyHonors(userId, entry));
      setOpen(false);
      onChanged();
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      Alert.alert("Couldn't save", typeof detail === "string" ? detail : "Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <View
      style={{
        backgroundColor: "#f0f4ff", borderRadius: 16, padding: 18,
        borderWidth: 1, borderColor: "#dbeafe", marginBottom: 16,
      }}
    >
      <Text style={{ color: "#94a3b8", fontSize: 11, fontWeight: "700", marginBottom: 5, letterSpacing: 0.8 }}>
        SCHREYER HONORS COLLEGE
      </Text>
      <Text style={{ color: "#1e3a8a", fontSize: 15, fontWeight: "700" }}>
        {honors ? "Schreyer Scholar" : "Not a Schreyer Scholar"}
      </Text>
      <Text style={{ color: "#64748b", fontSize: 12, lineHeight: 17, marginTop: 4, marginBottom: 10 }}>
        {honors
          ? `${entryLabel}. Your plan includes your honors thesis where your major lets it count toward electives.`
          : "In the Schreyer Honors College? Tell us so your plan can include your honors thesis."}
      </Text>

      <TouchableOpacity
        onPress={() => setOpen((o) => !o)}
        disabled={saving}
        style={{ alignSelf: "flex-start", paddingVertical: 6 }}
      >
        <Text style={{ color: "#2a5298", fontSize: 13, fontWeight: "700" }}>
          {open ? "Close" : honors ? "Change" : "I'm a Schreyer Scholar"}
        </Text>
      </TouchableOpacity>

      {open && (
        <View style={{ marginTop: 6 }}>
          {SCHREYER_ENTRIES.map((e) => (
            <TouchableOpacity
              key={e.value}
              onPress={() => choose(e.value)}
              disabled={saving}
              style={{
                paddingVertical: 10, paddingHorizontal: 12, borderRadius: 10, marginBottom: 6,
                backgroundColor: e.value === honors?.entry ? "#dbeafe" : "#ffffff",
                borderWidth: 1, borderColor: "#dbeafe",
              }}
            >
              <Text style={{ color: "#0f172a", fontSize: 13, fontWeight: "600" }}>{e.label}</Text>
            </TouchableOpacity>
          ))}
          {honors && (
            <TouchableOpacity onPress={() => choose(null)} disabled={saving} style={{ paddingVertical: 6 }}>
              <Text style={{ color: "#94a3b8", fontSize: 12 }}>I'm not a Schreyer Scholar</Text>
            </TouchableOpacity>
          )}
          {saving && <ActivityIndicator style={{ marginTop: 6 }} />}
        </View>
      )}
    </View>
  );
}
