import React, { useState, useCallback } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  ScrollView,
  Modal,
  TextInput,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as DocumentPicker from "expo-document-picker";
import { useFocusEffect, useRouter } from "expo-router";
import { useAuth } from "../../context/AuthContext";
import { NavHeader } from "../../components/NavHeader";
import { LoadingOverlay } from "../../components/LoadingOverlay";
import {
  uploadTranscript,
  getTranscript,
  deleteTranscript,
  addCourse,
  swapCourse,
  dropCourse,
  isOfficialAckError,
  type UploadResult,
  type TranscriptData,
  type TranscriptCourse,
} from "../../services/transcriptService";

export default function UploadScreen() {
  const { userId } = useAuth();
  const router = useRouter();

  const [transcript, setTranscript] = useState<TranscriptData | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [uploading,  setUploading]  = useState(false);
  const [deleting,   setDeleting]   = useState(false);
  const [result,     setResult]     = useState<UploadResult | null>(null);
  const [status,     setStatus]     = useState("Reading transcript…");

  // Manual class editing (in-progress courses only)
  type EditState = {
    mode: "add" | "swap";
    term: string;
    originalCode?: string;
    code: string;
    credits: string;
  };
  const [edit,   setEdit]   = useState<EditState | null>(null);
  const [saving, setSaving] = useState(false);

  async function refreshTranscript() {
    try {
      setTranscript(await getTranscript(userId!));
    } catch {
      /* leave the current view in place on a transient fetch error */
    }
  }

  function openAdd(term: string) {
    setEdit({ mode: "add", term, code: "", credits: "3" });
  }

  function openSwap(course: TranscriptCourse, term: string) {
    setEdit({
      mode: "swap",
      term,
      originalCode: course.course_code,
      code: course.course_code,
      credits: String(course.credits_earned),
    });
  }

  async function saveEdit() {
    if (!edit) return;
    const code = edit.code.trim();
    if (!code) { Alert.alert("Add a class", "Enter a course code, e.g. ETI 297."); return; }
    const credits = parseFloat(edit.credits);
    if (isNaN(credits) || credits <= 0) { Alert.alert("Add a class", "Enter valid credits (e.g. 3)."); return; }

    setSaving(true);
    try {
      if (edit.mode === "add") {
        await addCourse(userId!, code, edit.term, credits);
      } else {
        await swapCourse(userId!, edit.originalCode!, code, credits);
      }
      setEdit(null);
      await refreshTranscript();
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      Alert.alert("Couldn't save", typeof detail === "string" ? detail : "Something went wrong.");
    } finally {
      setSaving(false);
    }
  }

  function confirmDrop(course: TranscriptCourse) {
    Alert.alert(
      "Drop this class?",
      `Remove ${course.course_code} from your in-progress semester? This updates your audit and timeline.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Drop", style: "destructive",
          onPress: async () => {
            try {
              await dropCourse(userId!, course.course_code);
              await refreshTranscript();
            } catch (e: any) {
              const detail = e?.response?.data?.detail;
              Alert.alert("Couldn't drop", typeof detail === "string" ? detail : "Something went wrong.");
            }
          },
        },
      ],
    );
  }

  // Fetch transcript state whenever screen comes into focus
  useFocusEffect(useCallback(() => {
    let active = true;
    setResult(null);
    setLoading(true);

    getTranscript(userId!)
      .then((data) => { if (active) setTranscript(data); })
      .catch(() => { if (active) setTranscript({ has_transcript: false, courses_total: 0, terms: [] }); })
      .finally(() => { if (active) setLoading(false); });

    return () => { active = false; };
  }, [userId]));

  async function pickAndUpload() {
    const picked = await DocumentPicker.getDocumentAsync({
      type: "application/pdf",
      copyToCacheDirectory: true,
    });
    if (picked.canceled || !picked.assets?.length) return;
    await doUpload(picked.assets[0], false);
  }

  async function doUpload(file: DocumentPicker.DocumentPickerAsset, ack: boolean) {
    setStatus(ack ? "Importing courses…" : "Reading transcript…");
    setUploading(true);
    setResult(null);

    try {
      const data = await uploadTranscript(userId!, file.uri, file.name ?? "transcript.pdf", ack);
      setResult(data);
      setTimeout(() => router.navigate("/(tabs)/" as any), 1500);
    } catch (e: any) {
      // Official-transcript consent gate: warn, then re-upload with the ack flag.
      if (isOfficialAckError(e)) {
        Alert.alert(
          "Official transcript detected",
          "This looks like an OFFICIAL Penn State transcript. Official transcripts are meant for institutions - your unofficial transcript from LionPATH works just as well and is the recommended option.\n\nDo you want to use this file anyway?",
          [
            { text: "Cancel", style: "cancel" },
            { text: "Use it anyway", onPress: () => doUpload(file, true) },
          ],
        );
        return;
      }
      // The 409 detail is an object; guard so we never render "[object Object]".
      const detail = e?.response?.data?.detail;
      Alert.alert("Upload failed", typeof detail === "string" ? detail : "Something went wrong.");
    } finally {
      setUploading(false);
    }
  }

  function confirmDelete() {
    Alert.alert(
      "Delete transcript?",
      "This will remove all your parsed courses. Your timeline will reset to a projected plan until you upload a new transcript.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: handleDelete },
      ],
    );
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteTranscript(userId!);
      setTranscript({ has_transcript: false, courses_total: 0, terms: [] });
      // Refresh the timeline too
      router.navigate("/(tabs)/" as any);
    } catch {
      Alert.alert("Error", "Could not delete transcript. Please try again.");
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
        <NavHeader subtitle="Transcript" />
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator size="large" color="#1a3a6b" />
        </View>
      </SafeAreaView>
    );
  }

  // ── View mode: transcript exists ───────────────────────────────────────────
  if (transcript?.has_transcript) {
    return (
      <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
        <NavHeader subtitle="Transcript" />
        <ScrollView
          className="flex-1"
          contentContainerStyle={{ padding: 24, paddingBottom: 60 }}
          showsVerticalScrollIndicator={false}
        >
          {/* Header card */}
          <View style={{
            backgroundColor: "#1a3a6b", borderRadius: 20,
            padding: 22, marginBottom: 24,
          }}>
            <Text style={{ color: "#E8C84B", fontSize: 11, fontWeight: "800", letterSpacing: 1.5, marginBottom: 8 }}>
              YOUR TRANSCRIPT
            </Text>
            <Text style={{ color: "#ffffff", fontSize: 26, fontWeight: "900" }}>
              {transcript.courses_total} courses
            </Text>
            <Text style={{ color: "rgba(255,255,255,0.5)", fontSize: 13, marginTop: 4 }}>
              {transcript.terms.length} semester{transcript.terms.length !== 1 ? "s" : ""} on record
            </Text>
          </View>

          {/* Course list by term */}
          {transcript.terms.map((termGroup) => {
            // Only the in-progress semester is editable — a student can change
            // classes they're registered for, not rewrite graded history.
            const editable = termGroup.courses.some((c) => c.status === "in_progress");
            return (
            <View key={termGroup.term} style={{ marginBottom: 20 }}>
              <Text style={{
                color: "#94a3b8", fontSize: 11, fontWeight: "700",
                letterSpacing: 0.9, marginBottom: 10,
              }}>
                {termGroup.label.toUpperCase()}
              </Text>
              <View style={{
                backgroundColor: "#ffffff", borderRadius: 16,
                borderWidth: 1, borderColor: "#f1f5f9",
                overflow: "hidden",
              }}>
                {termGroup.courses.map((course, i) => {
                  const canEdit = editable && course.status === "in_progress";
                  return (
                  <View
                    key={course.course_code}
                    style={{
                      flexDirection: "row", alignItems: "center",
                      paddingVertical: 13, paddingHorizontal: 16,
                      borderBottomWidth: i < termGroup.courses.length - 1 ? 1 : 0,
                      borderBottomColor: "#f8fafc",
                    }}
                  >
                    <View style={{ flex: 1, flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Text style={{ color: "#1a3a6b", fontSize: 14, fontWeight: "700" }}>
                        {course.course_code}
                      </Text>
                      {course.source === "manual" && (
                        <Text style={{ color: "#2a5298", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 }}>
                          EDITED
                        </Text>
                      )}
                    </View>
                    {canEdit ? (
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
                        <Text style={{ color: "#94a3b8", fontSize: 11 }}>
                          {course.credits_earned} cr
                        </Text>
                        <TouchableOpacity onPress={() => openSwap(course, termGroup.term)} hitSlop={8}>
                          <Text style={{ color: "#2a5298", fontSize: 13, fontWeight: "700" }}>Swap</Text>
                        </TouchableOpacity>
                        <TouchableOpacity onPress={() => confirmDrop(course)} hitSlop={8}>
                          <Text style={{ color: "#e11d48", fontSize: 16, fontWeight: "700" }}>✕</Text>
                        </TouchableOpacity>
                      </View>
                    ) : (
                      <View style={{ alignItems: "flex-end", gap: 2 }}>
                        <Text style={{ color: "#374151", fontSize: 13, fontWeight: "600" }}>
                          {course.grade || "—"}
                        </Text>
                        <Text style={{ color: "#94a3b8", fontSize: 11 }}>
                          {course.credits_earned} cr
                        </Text>
                      </View>
                    )}
                  </View>
                  );
                })}
                {editable && (
                  <TouchableOpacity
                    onPress={() => openAdd(termGroup.term)}
                    style={{
                      paddingVertical: 12, paddingHorizontal: 16,
                      borderTopWidth: termGroup.courses.length > 0 ? 1 : 0,
                      borderTopColor: "#f1f5f9",
                    }}
                  >
                    <Text style={{ color: "#2a5298", fontSize: 13, fontWeight: "700" }}>
                      + Add a class
                    </Text>
                  </TouchableOpacity>
                )}
              </View>
            </View>
            );
          })}

          {/* Replace / Delete actions */}
          <View style={{ gap: 12, marginTop: 8 }}>
            <TouchableOpacity
              onPress={pickAndUpload}
              disabled={uploading || deleting}
              activeOpacity={0.85}
              style={{
                backgroundColor: "#1a3a6b", borderRadius: 14,
                paddingVertical: 15, alignItems: "center",
              }}
            >
              <Text style={{ color: "#ffffff", fontSize: 14, fontWeight: "700" }}>
                Replace transcript
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              onPress={confirmDelete}
              disabled={uploading || deleting}
              activeOpacity={0.85}
              style={{
                backgroundColor: "#fff1f2", borderRadius: 14,
                paddingVertical: 15, alignItems: "center",
                borderWidth: 1, borderColor: "#fecdd3",
              }}
            >
              {deleting ? (
                <ActivityIndicator color="#e11d48" size="small" />
              ) : (
                <Text style={{ color: "#e11d48", fontSize: 14, fontWeight: "700" }}>
                  Delete transcript
                </Text>
              )}
            </TouchableOpacity>
          </View>
        </ScrollView>

        {/* Add / swap class modal */}
        <Modal
          visible={edit !== null}
          transparent
          animationType="fade"
          onRequestClose={() => setEdit(null)}
        >
          <KeyboardAvoidingView
            behavior={Platform.OS === "ios" ? "padding" : undefined}
            style={{ flex: 1, justifyContent: "center", backgroundColor: "rgba(0,0,0,0.4)" }}
          >
            <View style={{
              marginHorizontal: 28, backgroundColor: "#ffffff",
              borderRadius: 20, padding: 22,
            }}>
              <Text style={{ color: "#1a3a6b", fontSize: 18, fontWeight: "900", marginBottom: 4 }}>
                {edit?.mode === "add" ? "Add a class" : "Swap class"}
              </Text>
              <Text style={{ color: "#94a3b8", fontSize: 12, marginBottom: 18 }}>
                {edit ? termLabelFor(transcript, edit.term) : ""} · in progress
              </Text>

              <Text style={{ color: "#64748b", fontSize: 11, fontWeight: "700", marginBottom: 6 }}>
                COURSE CODE
              </Text>
              <TextInput
                value={edit?.code ?? ""}
                onChangeText={(t) => setEdit((e) => (e ? { ...e, code: t } : e))}
                placeholder="e.g. ETI 297"
                autoCapitalize="characters"
                autoCorrect={false}
                style={{
                  borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 12,
                  paddingHorizontal: 14, paddingVertical: 12, fontSize: 15,
                  color: "#1a3a6b", marginBottom: 16,
                }}
              />

              <Text style={{ color: "#64748b", fontSize: 11, fontWeight: "700", marginBottom: 6 }}>
                CREDITS
              </Text>
              <TextInput
                value={edit?.credits ?? ""}
                onChangeText={(t) => setEdit((e) => (e ? { ...e, credits: t } : e))}
                placeholder="3"
                keyboardType="numeric"
                style={{
                  borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 12,
                  paddingHorizontal: 14, paddingVertical: 12, fontSize: 15,
                  color: "#1a3a6b", marginBottom: 22,
                }}
              />

              <View style={{ flexDirection: "row", gap: 12 }}>
                <TouchableOpacity
                  onPress={() => setEdit(null)}
                  disabled={saving}
                  style={{
                    flex: 1, paddingVertical: 13, borderRadius: 12,
                    alignItems: "center", backgroundColor: "#f1f5f9",
                  }}
                >
                  <Text style={{ color: "#64748b", fontSize: 14, fontWeight: "700" }}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={saveEdit}
                  disabled={saving}
                  style={{
                    flex: 1, paddingVertical: 13, borderRadius: 12,
                    alignItems: "center", backgroundColor: "#1a3a6b",
                  }}
                >
                  {saving
                    ? <ActivityIndicator color="#ffffff" size="small" />
                    : <Text style={{ color: "#ffffff", fontSize: 14, fontWeight: "700" }}>Save</Text>}
                </TouchableOpacity>
              </View>
            </View>
          </KeyboardAvoidingView>
        </Modal>

        <LoadingOverlay visible={uploading} label={status} />
      </SafeAreaView>
    );
  }

  // ── Upload mode: no transcript ─────────────────────────────────────────────
  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
      <NavHeader subtitle="Upload Transcript" />
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ padding: 24, paddingBottom: 60 }}
        showsVerticalScrollIndicator={false}
      >
        {/* Instruction card */}
        <View className="bg-blue-50 rounded-2xl px-5 py-4 mb-6 border border-blue-100">
          <Text className="text-navy font-bold text-sm mb-1">How to get your transcript</Text>
          <Text className="text-gray-500 text-xs leading-5">
            1. Log in to LionPATH{"\n"}
            2. Go to Academic Records → View Advising Transcript{"\n"}
            3. Save it as a PDF{"\n"}
            4. Upload it below
          </Text>
        </View>

        {/* Upload zone */}
        <TouchableOpacity
          onPress={pickAndUpload}
          disabled={uploading}
          activeOpacity={0.85}
          style={{
            borderWidth: 2,
            borderColor: uploading ? "#cbd5e1" : "#1a3a6b",
            borderStyle: "dashed",
            borderRadius: 20,
            paddingVertical: 44,
            alignItems: "center",
            backgroundColor: uploading ? "#f8fafc" : "#f0f4ff",
            marginBottom: 28,
          }}
        >
          {uploading ? (
            <>
              <ActivityIndicator color="#1a3a6b" size="large" />
              <Text className="text-navy-mid text-sm font-medium mt-4">Parsing transcript…</Text>
            </>
          ) : (
            <>
              <View
                style={{
                  width: 56, height: 56, borderRadius: 16,
                  backgroundColor: "#1a3a6b",
                  alignItems: "center", justifyContent: "center",
                  marginBottom: 14,
                }}
              >
                <Text style={{ color: "#ffffff", fontSize: 24 }}>↑</Text>
              </View>
              <Text className="text-navy font-bold text-base">Tap to upload PDF</Text>
              <Text className="text-gray-400 text-xs mt-1">Unofficial PSU transcript</Text>
            </>
          )}
        </TouchableOpacity>

        {/* Result */}
        {result && (
          <View className="rounded-2xl border border-gray-200 overflow-hidden">
            <View className="bg-green-50 px-5 py-4 border-b border-gray-100">
              <Text className="text-done font-bold text-base">Transcript uploaded</Text>
              <Text className="text-gray-400 text-xs mt-0.5">
                {result.courses_parsed} courses parsed successfully
              </Text>
            </View>
            <View className="flex-row">
              <StatBox label="Completed"   value={result.done}        color="#16a34a" />
              <View style={{ width: 1, backgroundColor: "#f3f4f6" }} />
              <StatBox label="In Progress" value={result.in_progress} color="#d97706" />
              {result.transfer > 0 && (
                <>
                  <View style={{ width: 1, backgroundColor: "#f3f4f6" }} />
                  <StatBox label="Transfer" value={result.transfer} color="#2a5298" />
                </>
              )}
            </View>
            {result.parse_warning && (
              <View className="px-5 py-3 border-t border-gray-100 bg-amber-50">
                <Text style={{ color: "#b45309", fontSize: 12 }}>{result.parse_warning}</Text>
              </View>
            )}
            <View className="px-5 py-3 border-t border-gray-100">
              <Text className="text-gray-400 text-xs">Returning to timeline…</Text>
            </View>
          </View>
        )}
      </ScrollView>
      <LoadingOverlay visible={uploading} label={status} />
    </SafeAreaView>
  );
}

function termLabelFor(transcript: TranscriptData | null, term: string): string {
  return transcript?.terms.find((t) => t.term === term)?.label ?? term;
}

function StatBox({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View className="flex-1 items-center py-5">
      <Text style={{ color, fontSize: 28, fontWeight: "700" }}>{value}</Text>
      <Text className="text-gray-400 text-xs mt-1">{label}</Text>
    </View>
  );
}
