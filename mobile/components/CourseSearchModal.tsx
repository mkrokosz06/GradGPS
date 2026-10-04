import React, { useEffect, useState } from "react";
import {
  View, Text, TouchableOpacity, Modal, TextInput, FlatList,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { searchAllCourses, type WalkCourse } from "../services/transcriptService";

/** Search every PSU course (optionally one gen-ed domain / subject) and pick one.
 *  Used by the no-transcript walkthrough's "add a class" and open plan slots. */
export function CourseSearchModal({
  visible, title, genEd, dept, suggested, exclude, onPick, onClose,
}: {
  visible:    boolean;
  title:      string;
  genEd?:     string | null;
  dept?:      string;
  suggested?: WalkCourse[];
  exclude?:   Set<string>;
  onPick:     (c: WalkCourse) => void;
  onClose:    () => void;
}) {
  const insets = useSafeAreaInsets();
  const [q, setQ]             = useState("");
  const [results, setResults] = useState<WalkCourse[]>([]);
  const [loading, setLoading] = useState(false);
  // A scoped search ("a GH course") may drop its scope, since the plan's label is only a hint.
  const [scoped, setScoped]   = useState(true);

  useEffect(() => {
    if (visible) { setQ(""); setResults([]); setScoped(true); }
  }, [visible]);

  useEffect(() => {
    const query = q.trim();
    if (!visible || !query) { setResults([]); return; }
    let active = true;
    setLoading(true);
    const t = setTimeout(() => {
      searchAllCourses(query, scoped ? { gen_ed: genEd, dept } : {})
        .then((r) => {
          if (active) setResults(r.map((c) => ({
            code: c.course_code, title: c.course_title, credits: c.credits,
          })));
        })
        .catch(() => { if (active) setResults([]); })
        .finally(() => { if (active) setLoading(false); });
    }, 250);
    return () => { active = false; clearTimeout(t); };
  }, [q, visible, scoped, genEd, dept]);

  const hasScope = !!(genEd || dept);
  const shown = (q.trim() ? results : (suggested ?? []))
    .filter((c) => !exclude?.has(c.code));

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1, backgroundColor: "#ffffff", paddingTop: insets.top + 12 }}
      >
        <View style={{ paddingHorizontal: 20, flexDirection: "row", alignItems: "center", marginBottom: 12 }}>
          <Text style={{ flex: 1, color: "#1a3a6b", fontSize: 18, fontWeight: "900" }}>{title}</Text>
          <TouchableOpacity onPress={onClose} hitSlop={10}>
            <Text style={{ color: "#64748b", fontSize: 15, fontWeight: "700" }}>Cancel</Text>
          </TouchableOpacity>
        </View>

        <View style={{ paddingHorizontal: 20 }}>
          <TextInput
            value={q}
            onChangeText={setQ}
            autoFocus
            placeholder="Course code or name, e.g. PSYCH 100"
            autoCapitalize="characters"
            autoCorrect={false}
            style={{
              borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 12,
              paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: "#1a3a6b",
            }}
          />
          {hasScope && (
            <TouchableOpacity onPress={() => setScoped((s) => !s)} style={{ marginTop: 8 }} hitSlop={6}>
              <Text style={{ color: "#2a5298", fontSize: 12, fontWeight: "700" }}>
                {scoped
                  ? `Showing ${genEd ? `${genEd} courses` : `${dept} courses`} only · search all courses`
                  : `Searching all courses · only ${genEd ? genEd : dept}`}
              </Text>
            </TouchableOpacity>
          )}
        </View>

        {!q.trim() && !!suggested?.length && (
          <Text style={{ paddingHorizontal: 20, marginTop: 16, color: "#94a3b8", fontSize: 11, fontWeight: "700", letterSpacing: 0.8 }}>
            SUGGESTED
          </Text>
        )}
        {loading && <ActivityIndicator style={{ marginTop: 16 }} color="#1a3a6b" />}

        <FlatList
          data={shown}
          keyExtractor={(c) => c.code}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: insets.bottom + 24 }}
          ListEmptyComponent={
            q.trim() && !loading ? (
              <Text style={{ color: "#94a3b8", fontSize: 13, marginTop: 16 }}>No courses match.</Text>
            ) : null
          }
          renderItem={({ item }) => (
            <TouchableOpacity
              onPress={() => onPick(item)}
              style={{ paddingVertical: 13, borderBottomWidth: 1, borderBottomColor: "#f1f5f9", flexDirection: "row", alignItems: "center" }}
            >
              <View style={{ flex: 1 }}>
                <Text style={{ color: "#1a3a6b", fontSize: 14, fontWeight: "700" }}>{item.code}</Text>
                {!!item.title && (
                  <Text style={{ color: "#64748b", fontSize: 12, marginTop: 2 }} numberOfLines={1}>{item.title}</Text>
                )}
              </View>
              {!!item.credits && (
                <Text style={{ color: "#94a3b8", fontSize: 11 }}>{item.credits} cr</Text>
              )}
            </TouchableOpacity>
          )}
        />
      </KeyboardAvoidingView>
    </Modal>
  );
}
