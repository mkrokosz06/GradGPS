import React, { useEffect, useState } from "react";
import {
  View, Text, TouchableOpacity, Modal, StyleSheet, ScrollView, ActivityIndicator, TextInput,
  FlatList, Dimensions,
} from "react-native";
import { TimelineCourse } from "../services/timelineService";
import { ChoicePayload } from "../services/userChoicesService";
import { searchSlotCourses, getGenEdDomains, getBreadthAreas, type SlotCourse, type GenEdDomain } from "../services/courseService";
import { useAuth } from "../context/AuthContext";

const WIN_H  = Dimensions.get("window").height;
const LIST_H = Math.round(WIN_H * 0.42);   // tall, scrollable results area

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
  const { userId } = useAuth();
  const options = course?.options ?? [];
  const searchable = !!course?.searchable;
  const isGenEd = course?.slot_kind === "gen_ed";
  const isBreadth = course?.pool_ref === "business_breadth";
  const useChips = isGenEd || isBreadth;   // pick a category/area chip, then a course
  const [selected, setSelected] = useState<string | null>(null);
  const [pinned, setPinned]     = useState(false);
  const [query, setQuery]       = useState("");
  const [results, setResults]   = useState<SlotCourse[]>([]);
  const [searching, setSearching] = useState(false);
  const [needsQuery, setNeedsQuery] = useState(false);
  const [domains, setDomains]   = useState<GenEdDomain[]>([]);
  const [activeCat, setActiveCat] = useState<string | null>(null);
  const [disclaimer, setDisclaimer] = useState<string>("");

  // Re-sync local state each time a new slot is opened. For gen-ed slots, load
  // the student's remaining domains (chips) and preselect the suggested one.
  useEffect(() => {
    if (!visible || !course) return;
    setSelected(course.chosen_code ?? null);
    setPinned(!!course.pinned);
    setQuery("");
    setResults([]);
    setNeedsQuery(false);
    setDomains([]);
    setDisclaimer("");

    const suggested = course.slot_key?.startsWith("gened:")
      ? course.slot_key.slice("gened:".length).split("#")[0].toUpperCase()
      : null;
    setActiveCat(suggested && suggested !== "GENERAL" ? suggested : null);

    if (isGenEd && userId) {
      getGenEdDomains(userId, course.slot_key ?? undefined)
        .then((ds) => {
          setDomains(ds);
          setActiveCat((cur) => {
            if (cur && ds.some((d) => d.code === cur)) return cur;
            return ds[0]?.code ?? null;   // generic slot → first remaining domain
          });
        })
        .catch(() => {});
    } else if (isBreadth && userId) {
      getBreadthAreas(userId)
        .then(({ areas, disclaimer: dc }) => {
          setDomains(areas.map((a) => ({ code: a.area, label: a.area })));
          setDisclaimer(dc || "");
          setActiveCat((cur) => cur ?? areas[0]?.area ?? null);   // first area
        })
        .catch(() => {});
    }
  }, [visible, course?.slot_key]);

  // Debounced course search for searchable slots (gen-ed by active domain; a
  // world-language pool searches its language courses directly).
  useEffect(() => {
    if (!visible || !searchable || !course?.slot_key || !userId) return;
    if (useChips && !activeCat) return;   // wait for the domain/area to resolve
    let active = true;
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const res = await searchSlotCourses(
          userId, course.slot_key!, query.trim(), useChips ? activeCat ?? undefined : undefined,
        );
        if (!active) return;
        setResults(res.results);
        setNeedsQuery(res.needs_query);
      } catch {
        if (active) { setResults([]); setNeedsQuery(false); }
      } finally {
        if (active) setSearching(false);
      }
    }, 250);
    return () => { active = false; clearTimeout(t); };
  }, [visible, searchable, course?.slot_key, query, userId, activeCat, isGenEd, isBreadth]);

  if (!course || !course.slot_key || !course.slot_kind) return null;

  const slotKey  = course.slot_key;
  const slotKind = course.slot_kind;
  const hasSwap  = options.length > 1;
  const canClear = !!course.chosen_code || !!course.pinned;

  const activeDomain = isGenEd ? domains.find((d) => d.code === activeCat) : undefined;
  const activeLabel = activeDomain?.label
    ?? (course.gen_ed_categories?.[0] ?? "").split(":")[0].trim();

  // Credits still needed for the active gen-ed domain — "1.5 cr still needed",
  // noting any credits already planned (selected) toward it.
  const fmtCr = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
  const creditsNote =
    activeDomain && activeDomain.remaining != null
      ? activeDomain.selected && activeDomain.selected > 0
        ? `${fmtCr(activeDomain.remaining)} cr still needed · ${fmtCr(activeDomain.selected)} selected`
        : `${fmtCr(activeDomain.remaining)} cr still needed`
      : "";

  const title = searchable
    ? isGenEd
      ? (activeLabel ? `Choose a ${activeLabel} course` : "Choose a gen-ed course")
      : isBreadth
      ? (activeLabel ? `${activeLabel} — pick a course` : "Choose a business breadth course")
      : course.course_code   // world-language pool: "World Language - Level Two…"
    : hasSwap ? "Choose your course" : course.course_code;
  const subtitle = searchable
    ? isBreadth
      ? "Pick an area, then a course from its two-piece sequence (6 cr from one area)."
      : "Search the courses that satisfy this requirement."
    : hasSwap ? "Pick which course fills this requirement."
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
        <View style={[styles.card, searchable && { maxHeight: Math.round(WIN_H * 0.9), maxWidth: 460 }]}>
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

          {searchable && (
            <View style={{ marginBottom: 8 }}>
              {useChips && domains.length > 0 && (
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  contentContainerStyle={{ paddingBottom: 8, gap: 6 }}
                >
                  {domains.map((d) => {
                    const on = d.code === activeCat;
                    return (
                      <TouchableOpacity
                        key={d.code}
                        onPress={() => setActiveCat(d.code)}
                        activeOpacity={0.7}
                        style={[styles.chip, on && styles.chipOn]}
                      >
                        <Text style={[styles.chipText, on && styles.chipTextOn]}>
                          {isBreadth ? d.label : d.code}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </ScrollView>
              )}
              {isGenEd && creditsNote ? (
                <Text style={styles.creditsNote}>{creditsNote}</Text>
              ) : null}
              {isBreadth && disclaimer ? (
                <Text style={styles.disclaimer}>{disclaimer}</Text>
              ) : null}

              <View style={styles.searchBar}>
                <Text style={styles.searchIcon}>⌕</Text>
                <TextInput
                  style={styles.searchInput}
                  placeholder="Search courses…"
                  placeholderTextColor="#94a3b8"
                  value={query}
                  onChangeText={setQuery}
                  autoCapitalize="characters"
                  autoCorrect={false}
                  returnKeyType="search"
                />
                {query.length > 0 && (
                  <TouchableOpacity onPress={() => setQuery("")} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                    <Text style={styles.searchClear}>✕</Text>
                  </TouchableOpacity>
                )}
              </View>

              {searching ? (
                <ActivityIndicator color="#1a3a6b" style={{ marginTop: 24, height: LIST_H }} />
              ) : needsQuery && !query.trim() ? (
                <Text style={[styles.searchHint, { height: LIST_H }]}>Type a course code or name to search.</Text>
              ) : results.length === 0 ? (
                <Text style={[styles.searchHint, { height: LIST_H }]}>
                  {query.trim() ? "No matching courses." : "No courses found."}
                </Text>
              ) : (
                <FlatList
                  style={{ height: LIST_H }}
                  data={results}
                  keyExtractor={(o, i) => `${o.course_code}_${i}`}
                  keyboardShouldPersistTaps="handled"
                  contentContainerStyle={{ paddingVertical: 4 }}
                  initialNumToRender={14}
                  windowSize={11}
                  renderItem={({ item: o }) => {
                    const active = selected ? selected.toUpperCase() === o.course_code.toUpperCase() : false;
                    return (
                      <TouchableOpacity
                        style={[styles.option, active && styles.optionActive]}
                        activeOpacity={0.7}
                        onPress={() => setSelected(active ? null : o.course_code)}
                      >
                        <Text style={[styles.radio, active && styles.radioActive]}>{active ? "◉" : "○"}</Text>
                        <View style={{ flex: 1 }}>
                          <Text style={[styles.optionCode, active && styles.optionCodeActive]}>{o.course_code}</Text>
                          {o.course_title ? (
                            <Text style={styles.optionTitle} numberOfLines={2}>{o.course_title}</Text>
                          ) : null}
                        </View>
                        <Text style={styles.optionCr}>{o.credits} cr</Text>
                      </TouchableOpacity>
                    );
                  }}
                />
              )}

              {selected && (
                <Text style={styles.selectedNote}>Selected: <Text style={styles.selectedCode}>{selected}</Text></Text>
              )}
            </View>
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
  optionTitle:      { fontSize: 12, color: "#64748b", marginTop: 2, lineHeight: 16 },
  optionCr:         { fontSize: 11, color: "#94a3b8", marginLeft: 8 },

  searchBar: {
    flexDirection: "row", alignItems: "center",
    borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 12,
    paddingHorizontal: 12, backgroundColor: "#f8fafc",
  },
  chip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: "#e2e8f0", backgroundColor: "#f8fafc",
  },
  chipOn:      { borderColor: "#1a3a6b", backgroundColor: "#1a3a6b" },
  chipText:    { fontSize: 12, fontWeight: "700", color: "#64748b" },
  chipTextOn:  { color: "#ffffff" },
  searchIcon:  { fontSize: 16, color: "#94a3b8", marginRight: 8 },
  searchInput: { flex: 1, paddingVertical: 11, fontSize: 14, color: "#111827" },
  searchClear: { fontSize: 13, color: "#94a3b8", paddingLeft: 8 },
  searchHint:  { fontSize: 13, color: "#94a3b8", textAlign: "center", marginTop: 16 },
  disclaimer:  { fontSize: 11, color: "#b45309", lineHeight: 15, marginBottom: 8 },
  creditsNote: { fontSize: 12, fontWeight: "700", color: "#1a3a6b", marginBottom: 8 },
  selectedNote: { fontSize: 12, color: "#64748b", marginTop: 2 },
  selectedCode: { color: "#1a3a6b", fontWeight: "700" },

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
