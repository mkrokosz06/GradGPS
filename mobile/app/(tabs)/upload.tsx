import React, { useState } from "react";
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
import axios from "axios";
import { API_BASE, USER_ID } from "../../constants/api";
import { NavHeader } from "../../components/NavHeader";

type UploadResult = {
  status: string;
  courses_parsed: number;
  done: number;
  in_progress: number;
  transfer: number;
};

export default function UploadScreen() {
  const [uploading, setUploading] = useState(false);
  const [result, setResult]       = useState<UploadResult | null>(null);

  async function pickAndUpload() {
    const picked = await DocumentPicker.getDocumentAsync({
      type: "application/pdf",
      copyToCacheDirectory: true,
    });
    if (picked.canceled || !picked.assets?.length) return;

    const file = picked.assets[0];
    setUploading(true);
    setResult(null);

    try {
      const form = new FormData();
      form.append("file", { uri: file.uri, name: file.name ?? "transcript.pdf", type: "application/pdf" } as any);
      const res = await axios.post<UploadResult>(`${API_BASE}/transcript/upload`, form, {
        headers: { "x-user-id": USER_ID, "Content-Type": "multipart/form-data" },
      });
      setResult(res.data);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.response?.data?.detail ?? "Something went wrong.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top","left","right"]}>
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
            2. Go to Student Center → My Academics{"\n"}
            3. Download your Unofficial Transcript as a PDF{"\n"}
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
            {/* Success header */}
            <View className="bg-green-50 px-5 py-4 border-b border-gray-100">
              <Text className="text-done font-bold text-base">Transcript uploaded</Text>
              <Text className="text-gray-400 text-xs mt-0.5">
                {result.courses_parsed} courses parsed successfully
              </Text>
            </View>

            {/* Stats */}
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

            {/* Footer note */}
            <View className="px-5 py-3 border-t border-gray-100">
              <Text className="text-gray-400 text-xs">
                Return to Timeline and pull down to refresh your degree audit.
              </Text>
            </View>
          </View>
        )}
      </ScrollView>
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
