import React, { useEffect, useState } from "react";
import {
  View, Text, TouchableOpacity, Modal, StyleSheet, ScrollView, ActivityIndicator,
} from "react-native";
import { TimelineCourse } from "../services/timelineService";
import { ChoicePayload } from "../services/userChoicesService";

/**
 * Class selector — long-press (or tap the affordance on) a suggested course to
 * lock in which course fills the slot and/or which semester it lands in.
 * Course swaps are offered only when the slot carries bounded `options`
 * (choose-one pairs, anchored pools); pinning works for any slot with a slot_key.
 */
export function CoursePickerModal({
  visible,
  course,
  term,
  termLabel,
  busy,
  onApply,
  onClear,
  onClose,
}: {
  visible: boolean;
  course: TimelineCourse | null;
  term: string;
  termLabel: string;
  busy: boolean;
  onApply: (payload: ChoicePayload) => void;
  onClear: (slotKey: string) => void;
  onClose: () => void;
}) {
  const options = course?.options ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const [pinned, setPinned]     = useState(false);

  // Re-sync local state each time a new slot is opened.
  useEffect(() => {
    if (visible && course) {
      setSelected(course.chosen_code ?? null);
      setPinned(!!course.pinned);
    }
  }, [visible, course]);

  if (!course || !course.slot_key || !course.slot_kind) return null;

  const slotKey  = course.slot_key;
  const slotKind = course.slot_kind;
  const hasSwap  = options.length > 1;
  const canClear = !!course.chosen_code || !!course.pinned;

  const title = hasSwap ? "Choose your course" : course.course_code;
  const subtitle = hasSwap
    ? "Pick which course fills this requirement."
    : course.course_title || "Lock this into a semester.";

  function save() {
    const payload: ChoicePayload = { slot_key: slotKey, slot_kind: slotKind };
    if (selected) payload.chosen_course = selected;
    if (pinned)   payload.pinned_term   = term;
    if (!payload.chosen_course && !payload.pinned_term) {
      onClear(slotKey);          // nothing selected — same as letting GradGPS decide
    } else {
      onApply(payload);
    }
  }

  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>

          {hasSwap && (
            <ScrollView style={styles.optionList} contentContainerStyle={{ paddingVertical: 4 }}>
              {options.map((o, i) => {
                const active = selected
                  ? selected.toUpperCase() === o.course_code.toUpperCase()
                  : false;
                return (
                  <TouchableOpacity
                    key={`${o.course_code}_${i}`}
                    style={[styles.option, active && styles.optionActive]}
                    activeOpacity={0.7}
                    onPress={() => setSelected(active ? null : o.course_code)}
                  >
                    <Text style={[styles.radio, active && styles.radioActive]}>
                      {active ? "◉" : "○"}
                    </Text>
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.optionCode, active && styles.optionCodeActive]}>
                        {o.course_code}
                      </Text>
                      {o.course_title ? (
                        <Text style={styles.optionTitle} numberOfLines={1}>{o.course_title}</Text>
                      ) : null}
                    </View>
                    <Text style={styles.optionCr}>{o.credits} cr</Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          )}

          {/* Pin toggle */}
          <TouchableOpacity
            style={[styles.pinRow, pinned && styles.pinRowActive]}
            activeOpacity={0.7}
            onPress={() => setPinned(p => !p)}
          >
            <Text style={[styles.pinGlyph, pinned && styles.pinGlyphActive]}>📌</Text>
            <Text style={[styles.pinText, pinned && styles.pinTextActive]}>
              {pinned ? `Locked to ${termLabel}` : `Lock to ${termLabel}`}
            </Text>
            <Text style={[styles.pinCheck, pinned && styles.pinCheckActive]}>{pinned ? "✓" : ""}</Text>
          </TouchableOpacity>
          {course.pin_moved ? (
            <Text style={styles.note}>
              Your pinned term had already passed, so this moved to the earliest upcoming semester.
            </Text>
          ) : null}

          {/* Actions */}
          <TouchableOpacity style={styles.primaryBtn} onPress={save} activeOpacity={0.85} disabled={busy}>
            {busy ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.primaryBtnText}>Save</Text>}
          </TouchableOpacity>
          {canClear && (
            <TouchableOpacity
              style={styles.secondaryBtn}
              onPress={() => onClear(slotKey)}
              activeOpacity={0.7}
              disabled={busy}
            >
              <Text style={styles.secondaryBtnText}>Let GradGPS choose</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity style={styles.cancelBtn} onPress={onClose} activeOpacity={0.7} disabled={busy}>
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
    paddingVertical: 24, paddingHorizontal: 22, width: "100%", maxWidth: 400,
  },
  title:    { fontSize: 18, fontWeight: "800", color: "#0f172a", marginBottom: 4 },
  subtitle: { fontSize: 13, lineHeight: 19, color: "#64748b", marginBottom: 16 },

  optionList: { maxHeight: 260, marginBottom: 8 },
  option: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 11, paddingHorizontal: 12,
    borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0", marginBottom: 8,
  },
  optionActive: { borderColor: "#1a3a6b", backgroundColor: "#eff4fb" },
  radio:        { fontSize: 16, color: "#cbd5e1", marginRight: 10 },
  radioActive:  { color: "#1a3a6b" },
  optionCode:       { fontSize: 14, fontWeight: "700", color: "#334155" },
  optionCodeActive: { color: "#1a3a6b" },
  optionTitle:      { fontSize: 11, color: "#94a3b8", marginTop: 1 },
  optionCr:         { fontSize: 11, color: "#94a3b8", marginLeft: 8 },

  pinRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 12, paddingHorizontal: 12,
    borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0", marginTop: 4, marginBottom: 4,
  },
  pinRowActive:  { borderColor: "#1a3a6b", backgroundColor: "#eff4fb" },
  pinGlyph:      { fontSize: 15, marginRight: 10, opacity: 0.4 },
  pinGlyphActive:{ opacity: 1 },
  pinText:       { flex: 1, fontSize: 14, fontWeight: "600", color: "#64748b" },
  pinTextActive: { color: "#1a3a6b" },
  pinCheck:      { fontSize: 14, fontWeight: "800", color: "transparent" },
  pinCheckActive:{ color: "#1a3a6b" },

  note: { fontSize: 11, color: "#b45309", marginTop: 6, marginBottom: 2, lineHeight: 16 },

  primaryBtn: {
    backgroundColor: "#1a3a6b", borderRadius: 14,
    paddingVertical: 15, alignItems: "center", marginTop: 12, marginBottom: 8,
  },
  primaryBtnText: { color: "#ffffff", fontSize: 15, fontWeight: "700" },
  secondaryBtn:     { paddingVertical: 10, alignItems: "center" },
  secondaryBtnText: { color: "#64748b", fontSize: 13, fontWeight: "600" },
  cancelBtn:     { paddingVertical: 6, alignItems: "center" },
  cancelBtnText: { color: "#94a3b8", fontSize: 13, fontWeight: "600" },
});
