import React, { useEffect, useState } from "react";
import {
  View, Text, TouchableOpacity, Modal, StyleSheet, FlatList,
  ActivityIndicator, Dimensions,
} from "react-native";
import {
  getCandidates, putSubstitution, deleteSubstitution, substitutionErrorMessage,
  type SubstitutionCandidate,
} from "../services/substitutionService";
import { useAuth } from "../context/AuthContext";

const WIN_H  = Dimensions.get("window").height;
const LIST_H = Math.round(WIN_H * 0.42);

/**
 * "I already took a class that counts for this."
 *
 * The advisor workaround: a department accepts a course in place of a
 * requirement (ESC 120 "Design for Failure" for CHE 100), but the catalog only
 * knows the requirement's own code, so GradGPS keeps scheduling a course the
 * student never has to take. Picking the real course here declares a personal
 * equivalence; the audit and timeline honour it on their next fetch.
 *
 * Candidates are the student's own transcript courses, ones the audit hasn't
 * already credited listed first — that's almost always the one their adviser
 * approved.
 */
export function SubstitutionModal({
  visible,
  requirementCode,
  requirementTitle,
  onSaved,
  onClose,
}: {
  visible: boolean;
  requirementCode: string | null;
  requirementTitle?: string;
  /** Called after a successful save/clear so the caller can refetch. */
  onSaved: () => void | Promise<void>;
  onClose: () => void;
}) {
  const { userId } = useAuth();
  const [loading, setLoading]       = useState(false);
  const [saving, setSaving]         = useState(false);
  const [candidates, setCandidates] = useState<SubstitutionCandidate[]>([]);
  const [current, setCurrent]       = useState<string | null>(null);
  const [selected, setSelected]     = useState<string | null>(null);
  const [error, setError]           = useState("");

  useEffect(() => {
    if (!visible || !requirementCode || !userId) return;
    let active = true;
    setLoading(true);
    setError("");
    setCandidates([]);
    getCandidates(userId, requirementCode)
      .then((res) => {
        if (!active) return;
        setCandidates(res.candidates);
        setCurrent(res.current);
        setSelected(res.current);
      })
      .catch(() => { if (active) setError("Couldn't load your courses."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [visible, requirementCode, userId]);

  if (!requirementCode) return null;

  async function save() {
    if (!userId || !requirementCode || !selected) return;
    setSaving(true);
    setError("");
    try {
      await putSubstitution(userId, requirementCode, selected);
      await onSaved();
      onClose();
    } catch (e) {
      setError(substitutionErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    if (!userId || !requirementCode) return;
    setSaving(true);
    setError("");
    try {
      await deleteSubstitution(userId, requirementCode);
      await onSaved();
      onClose();
    } catch (e) {
      setError(substitutionErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  const unusedCount = candidates.filter((c) => !c.already_used).length;

  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Text style={styles.title}>What counts for {requirementCode}?</Text>
          <Text style={styles.subtitle}>
            {requirementTitle ? `${requirementTitle}\n` : ""}
            Pick the class you already took that your adviser accepts in its place.
            GradGPS will stop asking you to take {requirementCode}.
          </Text>

          {loading ? (
            <ActivityIndicator color="#1a3a6b" style={{ height: LIST_H }} />
          ) : candidates.length === 0 ? (
            <Text style={[styles.hint, { height: LIST_H }]}>
              No courses on your transcript yet — upload your transcript first.
            </Text>
          ) : (
            <FlatList
              style={{ height: LIST_H }}
              data={candidates}
              keyExtractor={(c, i) => `${c.course_code}_${i}`}
              contentContainerStyle={{ paddingVertical: 4 }}
              initialNumToRender={14}
              windowSize={11}
              ListHeaderComponent={
                unusedCount > 0 ? (
                  <Text style={styles.sectionNote}>
                    Courses not already counted toward a requirement are listed first.
                  </Text>
                ) : null
              }
              renderItem={({ item: c }) => {
                const active = selected?.toUpperCase() === c.course_code.toUpperCase();
                return (
                  <TouchableOpacity
                    style={[styles.option, active && styles.optionActive]}
                    activeOpacity={0.7}
                    onPress={() => setSelected(active ? null : c.course_code)}
                  >
                    <Text style={[styles.radio, active && styles.radioActive]}>
                      {active ? "◉" : "○"}
                    </Text>
                    <View style={{ flex: 1 }}>
                      <View style={styles.codeRow}>
                        <Text style={[styles.optionCode, active && styles.optionCodeActive]}>
                          {c.course_code}
                        </Text>
                        {c.already_used ? (
                          <View style={styles.usedBadge}>
                            <Text style={styles.usedBadgeText}>ALREADY COUNTED</Text>
                          </View>
                        ) : null}
                      </View>
                      {c.course_title ? (
                        <Text style={styles.optionTitle} numberOfLines={2}>{c.course_title}</Text>
                      ) : null}
                      <Text style={styles.optionMeta}>
                        {[c.term, c.grade || (c.status === "in_progress" ? "in progress" : ""), `${c.credits} cr`]
                          .filter(Boolean)
                          .join(" · ")}
                      </Text>
                    </View>
                  </TouchableOpacity>
                );
              }}
            />
          )}

          <Text style={styles.disclaimer}>
            This is your own declaration, not an approved exception — confirm it with
            your adviser before you register.
          </Text>
          {error ? <Text style={styles.error}>{error}</Text> : null}

          <TouchableOpacity
            style={[styles.primaryBtn, !selected && styles.primaryBtnOff]}
            onPress={save}
            activeOpacity={0.85}
            disabled={saving || !selected}
          >
            {saving ? (
              <ActivityIndicator color="#ffffff" />
            ) : (
              <Text style={styles.primaryBtnText}>
                {selected ? `${selected} counts for ${requirementCode}` : "Pick a class"}
              </Text>
            )}
          </TouchableOpacity>

          {current ? (
            <TouchableOpacity style={styles.secondaryBtn} onPress={clear} activeOpacity={0.7} disabled={saving}>
              <Text style={styles.secondaryBtnText}>Remove this substitution</Text>
            </TouchableOpacity>
          ) : null}
          <TouchableOpacity style={styles.cancelBtn} onPress={onClose} activeOpacity={0.7} disabled={saving}>
            <Text style={styles.cancelBtnText}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center", justifyContent: "center", paddingHorizontal: 28,
  },
  card: {
    backgroundColor: "#ffffff", borderRadius: 20,
    paddingVertical: 24, paddingHorizontal: 22,
    width: "100%", maxWidth: 460, maxHeight: Math.round(WIN_H * 0.9),
  },
  title:    { fontSize: 18, fontWeight: "800", color: "#0f172a", marginBottom: 4 },
  subtitle: { fontSize: 13, lineHeight: 19, color: "#64748b", marginBottom: 14 },

  sectionNote: { fontSize: 11, color: "#94a3b8", marginBottom: 8, lineHeight: 15 },
  option: {
    flexDirection: "row", alignItems: "flex-start",
    paddingVertical: 11, paddingHorizontal: 12,
    borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0", marginBottom: 8,
  },
  optionActive: { borderColor: "#1a3a6b", backgroundColor: "#eff4fb" },
  radio:        { fontSize: 16, color: "#cbd5e1", marginRight: 10, marginTop: 1 },
  radioActive:  { color: "#1a3a6b" },
  codeRow:          { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6 },
  optionCode:       { fontSize: 14, fontWeight: "700", color: "#334155" },
  optionCodeActive: { color: "#1a3a6b" },
  optionTitle:      { fontSize: 12, color: "#64748b", marginTop: 2, lineHeight: 16 },
  optionMeta:       { fontSize: 11, color: "#94a3b8", marginTop: 3 },
  usedBadge: {
    backgroundColor: "#fef3c7", borderRadius: 6,
    paddingHorizontal: 6, paddingVertical: 2,
  },
  usedBadgeText: { fontSize: 9, fontWeight: "800", color: "#b45309", letterSpacing: 0.4 },

  hint:       { fontSize: 13, color: "#94a3b8", textAlign: "center", marginTop: 16 },
  disclaimer: { fontSize: 11, color: "#b45309", lineHeight: 15, marginTop: 6 },
  error:      { fontSize: 12, color: "#dc2626", lineHeight: 17, marginTop: 8 },

  primaryBtn: {
    backgroundColor: "#1a3a6b", borderRadius: 14,
    paddingVertical: 15, alignItems: "center", marginTop: 12, marginBottom: 8,
  },
  primaryBtnOff:  { backgroundColor: "#cbd5e1" },
  primaryBtnText: { color: "#ffffff", fontSize: 14, fontWeight: "700" },
  secondaryBtn:     { paddingVertical: 10, alignItems: "center" },
  secondaryBtnText: { color: "#64748b", fontSize: 13, fontWeight: "600" },
  cancelBtn:     { paddingVertical: 6, alignItems: "center" },
  cancelBtnText: { color: "#94a3b8", fontSize: 13, fontWeight: "600" },
});
