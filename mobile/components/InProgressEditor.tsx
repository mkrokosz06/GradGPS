import React, { useCallback, useState } from "react";
import {
  Modal, View, Text, TextInput, TouchableOpacity, Alert, ActivityIndicator, Platform,
} from "react-native";
import { swapCourse, dropCourse } from "../services/transcriptService";

/**
 * Shared editor for in-progress (transcript) courses, used from the Home and
 * Timeline cards so a student can swap or drop a class they're registered for
 * without going to the transcript screen. Backed by the same
 * PATCH/DELETE /transcript/course endpoints as upload.tsx.
 *
 * Usage:
 *   const { openMenu, modal } = useInProgressEditor(userId, reload);
 *   // on an in-progress card: onPress/onLongPress={() => openMenu(course)}
 *   // render {modal} once at the screen root
 */
export type EditableCourse = { course_code: string; credits_earned?: number };

function errMessage(e: any): string {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Something went wrong.";
}

export function useInProgressEditor(userId: string | null, onChanged: () => void) {
  const [swap, setSwap]   = useState<{ originalCode: string; code: string; credits: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const confirmDrop = useCallback((code: string) => {
    Alert.alert(
      "Drop this class?",
      `Remove ${code} from your in-progress semester? This updates your audit and timeline.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Drop", style: "destructive",
          onPress: async () => {
            try {
              await dropCourse(userId!, code);
              onChanged();
            } catch (e) {
              Alert.alert("Couldn't drop", errMessage(e));
            }
          },
        },
      ],
    );
  }, [userId, onChanged]);

  const openMenu = useCallback((course: EditableCourse) => {
    Alert.alert(
      course.course_code,
      "Update this in-progress class?",
      [
        {
          text: "Swap for another",
          onPress: () => setSwap({
            originalCode: course.course_code,
            code: course.course_code,
            credits: String(course.credits_earned && course.credits_earned > 0 ? course.credits_earned : 3),
          }),
        },
        { text: "Drop class", style: "destructive", onPress: () => confirmDrop(course.course_code) },
        { text: "Cancel", style: "cancel" },
      ],
    );
  }, [confirmDrop]);

  const save = useCallback(async () => {
    if (!swap) return;
    const code = swap.code.trim();
    if (!code) { Alert.alert("Swap class", "Enter a course code, e.g. IST 210."); return; }
    const credits = parseFloat(swap.credits);
    if (isNaN(credits) || credits <= 0) { Alert.alert("Swap class", "Enter valid credits (e.g. 3)."); return; }

    setSaving(true);
    try {
      await swapCourse(userId!, swap.originalCode, code, credits);
      setSwap(null);
      onChanged();
    } catch (e) {
      Alert.alert("Couldn't save", errMessage(e));
    } finally {
      setSaving(false);
    }
  }, [swap, userId, onChanged]);

  const modal = (
    <Modal visible={!!swap} transparent animationType="fade" onRequestClose={() => setSwap(null)}>
      <View style={{ flex: 1, backgroundColor: "rgba(15,23,42,0.45)", justifyContent: "center", padding: 24 }}>
        <View style={{ backgroundColor: "#ffffff", borderRadius: 16, padding: 20 }}>
          <Text style={{ color: "#1a3a6b", fontSize: 18, fontWeight: "800" }}>Swap class</Text>
          <Text style={{ color: "#64748b", fontSize: 13, marginTop: 4 }}>
            Replacing {swap?.originalCode}. Enter the class you're taking instead.
          </Text>

          <Text style={{ color: "#334155", fontSize: 12, fontWeight: "700", marginTop: 16 }}>Course code</Text>
          <TextInput
            value={swap?.code ?? ""}
            onChangeText={(t) => setSwap((s) => (s ? { ...s, code: t.toUpperCase() } : s))}
            autoCapitalize="characters"
            autoCorrect={false}
            placeholder="e.g. IST 210"
            placeholderTextColor="#94a3b8"
            style={{
              borderWidth: 1, borderColor: "#dbe6f5", borderRadius: 10,
              paddingHorizontal: 12, paddingVertical: Platform.OS === "ios" ? 12 : 8,
              fontSize: 16, color: "#0f172a", marginTop: 6,
            }}
          />

          <Text style={{ color: "#334155", fontSize: 12, fontWeight: "700", marginTop: 14 }}>Credits</Text>
          <TextInput
            value={swap?.credits ?? ""}
            onChangeText={(t) => setSwap((s) => (s ? { ...s, credits: t.replace(/[^0-9.]/g, "") } : s))}
            keyboardType="decimal-pad"
            placeholder="3"
            placeholderTextColor="#94a3b8"
            style={{
              borderWidth: 1, borderColor: "#dbe6f5", borderRadius: 10,
              paddingHorizontal: 12, paddingVertical: Platform.OS === "ios" ? 12 : 8,
              fontSize: 16, color: "#0f172a", marginTop: 6, width: 100,
            }}
          />

          <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
            <TouchableOpacity onPress={() => setSwap(null)} disabled={saving} style={{ paddingVertical: 10, paddingHorizontal: 16 }}>
              <Text style={{ color: "#64748b", fontSize: 15, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={save}
              disabled={saving}
              style={{ backgroundColor: "#1a3a6b", borderRadius: 10, paddingVertical: 10, paddingHorizontal: 20, minWidth: 92, alignItems: "center" }}
            >
              {saving ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontSize: 15, fontWeight: "700" }}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );

  return { openMenu, modal };
}
