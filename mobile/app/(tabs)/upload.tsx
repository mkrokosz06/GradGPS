import React, { useState, useCallback } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  ScrollView,
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
  isOfficialAckError,
  type UploadResult,
  type TranscriptData,
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
          {transcript.terms.map((termGroup) => (
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
                {termGroup.courses.map((course, i) => (
                  <View
                    key={course.course_code}
                    style={{
                      flexDirection: "row", alignItems: "center",
                      paddingVertical: 13, paddingHorizontal: 16,
                      borderBottomWidth: i < termGroup.courses.length - 1 ? 1 : 0,
                      borderBottomColor: "#f8fafc",
                    }}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={{ color: "#1a3a6b", fontSize: 14, fontWeight: "700" }}>
                        {course.course_code}
                      </Text>
                    </View>
                    <View style={{ alignItems: "flex-end", gap: 2 }}>
                      <Text style={{ color: "#374151", fontSize: 13, fontWeight: "600" }}>
                        {course.grade || "—"}
                      </Text>
                      <Text style={{ color: "#94a3b8", fontSize: 11 }}>
                        {course.credits_earned} cr
                      </Text>
                    </View>
                  </View>
                ))}
              </View>
            </View>
          ))}

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

function StatBox({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View className="flex-1 items-center py-5">
      <Text style={{ color, fontSize: 28, fontWeight: "700" }}>{value}</Text>
      <Text className="text-gray-400 text-xs mt-1">{label}</Text>
    </View>
  );
}
