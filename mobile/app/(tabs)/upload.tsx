import React, { useState } from "react";
import { View, Text, TouchableOpacity, ActivityIndicator, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as DocumentPicker from "expo-document-picker";
import axios from "axios";
import { API_BASE, USER_ID } from "../../constants/api";

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
      form.append("file", {
        uri:  file.uri,
        name: file.name ?? "transcript.pdf",
        type: "application/pdf",
      } as any);

      const res = await axios.post<UploadResult>(`${API_BASE}/transcript/upload`, form, {
        headers: {
          "x-user-id":    USER_ID,
          "Content-Type": "multipart/form-data",
        },
      });
      setResult(res.data);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.response?.data?.detail ?? "Something went wrong.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-navy px-6">
      <Text className="text-gold font-bold text-2xl mt-6 mb-2">Upload Transcript</Text>
      <Text className="text-slate-400 text-sm mb-8">
        Download your unofficial PSU transcript from Student Aid and upload it here.
      </Text>

      <TouchableOpacity
        onPress={pickAndUpload}
        disabled={uploading}
        className="bg-gold rounded-2xl py-5 items-center mb-6"
        activeOpacity={0.8}
      >
        {uploading ? (
          <ActivityIndicator color="#1a3a6b" />
        ) : (
          <>
            <Text className="text-4xl mb-1">📄</Text>
            <Text className="text-navy font-bold text-lg">Choose PDF</Text>
          </>
        )}
      </TouchableOpacity>

      {result && (
        <View className="bg-navy-light/30 rounded-2xl p-5 border border-slate-700">
          <Text className="text-done font-bold text-lg mb-3">✓ Uploaded successfully</Text>
          <View className="gap-2">
            <Row label="Courses parsed" value={result.courses_parsed} />
            <Row label="Completed"      value={result.done} />
            <Row label="In progress"    value={result.in_progress} />
            {result.transfer > 0 && <Row label="Transfer" value={result.transfer} />}
          </View>
          <Text className="text-slate-400 text-xs mt-4">
            Pull down on the Audit tab to refresh your results.
          </Text>
        </View>
      )}
    </SafeAreaView>
  );
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <View className="flex-row justify-between">
      <Text className="text-slate-300">{label}</Text>
      <Text className="text-white font-semibold">{value}</Text>
    </View>
  );
}
