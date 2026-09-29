import React, { useEffect, useState } from "react";
import { View, Text, TouchableOpacity, ActivityIndicator, Alert } from "react-native";
import { getFocusAreas, getMyFocus, setMyFocus, type FocusArea } from "../services/focusService";

/**
 * Account-page card for a major that requires an Application Focus (ETI, Data
 * Sciences, HCDD, Cybersecurity, IT Ethics). Renders nothing for any other major.
 *
 * Picking an area tells the audit which list counts — before that it accepts any
 * mix of every area's courses — and the plan's "Application Focus Selection"
 * slots then offer that area's courses in the picker.
 */
export function ApplicationFocusCard({
  userId, major, onChanged,
}: { userId: string; major: string; onChanged: () => void }) {
  const [areas, setAreas] = useState<FocusArea[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([getFocusAreas(userId, major), getMyFocus(userId)])
      .then(([a, f]) => { if (active) { setAreas(a); setFocus(f); } })
      .catch(() => {});
    return () => { active = false; };
  }, [userId, major]);

  if (areas.length === 0) return null;
  const chosen = areas.find((a) => a.name === focus);
  const credits = (chosen ?? areas[0]).credits;

  async function choose(name: string | null) {
    setSaving(true);
    try {
      const saved = await setMyFocus(userId, name);
      setFocus(saved);
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
        APPLICATION FOCUS
      </Text>
      <Text style={{ color: "#1e3a8a", fontSize: 15, fontWeight: "700" }}>
        {chosen ? chosen.name : "Not chosen yet"}
      </Text>
      <Text style={{ color: "#64748b", fontSize: 12, lineHeight: 17, marginTop: 4, marginBottom: 10 }}>
        {chosen
          ? `${credits} credits from this area count toward your major.`
          : "Your major requires credits from one focus area. Pick yours so your plan shows its courses."}
      </Text>

      <TouchableOpacity
        onPress={() => setOpen((o) => !o)}
        disabled={saving}
        style={{ alignSelf: "flex-start", paddingVertical: 6 }}
      >
        <Text style={{ color: "#2a5298", fontSize: 13, fontWeight: "700" }}>
          {open ? "Close" : chosen ? "Change focus" : "Choose a focus"}
        </Text>
      </TouchableOpacity>

      {open && (
        <View style={{ marginTop: 6 }}>
          {areas.map((a) => (
            <TouchableOpacity
              key={a.name}
              onPress={() => choose(a.name)}
              disabled={saving}
              style={{
                paddingVertical: 10, paddingHorizontal: 12, borderRadius: 10, marginBottom: 6,
                backgroundColor: a.name === focus ? "#dbeafe" : "#ffffff",
                borderWidth: 1, borderColor: "#dbeafe",
              }}
            >
              <Text style={{ color: "#0f172a", fontSize: 13, fontWeight: "600" }}>{a.name}</Text>
              <Text style={{ color: "#64748b", fontSize: 11, marginTop: 2 }} numberOfLines={1}>
                {a.credits} cr · {a.courses.slice(0, 4).join(", ")}{a.courses.length > 4 ? "…" : ""}
              </Text>
            </TouchableOpacity>
          ))}
          {focus && (
            <TouchableOpacity onPress={() => choose(null)} disabled={saving} style={{ paddingVertical: 6 }}>
              <Text style={{ color: "#94a3b8", fontSize: 12 }}>Clear my focus</Text>
            </TouchableOpacity>
          )}
          {saving && <ActivityIndicator style={{ marginTop: 6 }} />}
        </View>
      )}
    </View>
  );
}
