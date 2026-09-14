import React, { useEffect, useState, useMemo } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  getCourseDetail,
  type CourseDetail,
} from "../../services/courseService";

// ── Description (first 2 sentences + expand) ─────────────────────────────────

function splitSentences(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  // Split on sentence-ending punctuation followed by whitespace + a capital letter
  // (or end of string). Keeps abbreviations like "U.S." from over-splitting when
  // the next token isn't capitalized as a new sentence.
  const parts = trimmed.match(/[^.!?]+[.!?]+(?:\s+|$)|[^.!?]+$/g);
  if (!parts) return [trimmed];
  return parts.map((s) => s.trim()).filter(Boolean);
}

function CourseDescription({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const sentences = useMemo(() => splitSentences(text), [text]);
  const needsExpand = sentences.length > 2;
  const preview = sentences.slice(0, 2).join(" ");

  // Reset when navigating to a different course's description
  useEffect(() => {
    setExpanded(false);
  }, [text]);

  return (
    <View>
      <Text style={{ fontSize: 13, color: "#64748b", lineHeight: 20 }}>
        {expanded || !needsExpand ? text : preview}
      </Text>
      {needsExpand ? (
        <TouchableOpacity
          onPress={() => setExpanded((e) => !e)}
          activeOpacity={0.7}
          hitSlop={{ top: 8, bottom: 8, left: 4, right: 4 }}
          style={{ marginTop: 6, flexDirection: "row", alignItems: "center" }}
        >
          <Text style={{ fontSize: 12, color: "#94a3b8", marginRight: 4 }}>
            {expanded ? "▾" : "▸"}
          </Text>
          <Text style={{ fontSize: 13, fontWeight: "600", color: "#1a3a6b" }}>
            {expanded ? "Show less" : "Read more"}
          </Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export default function CourseDetailScreen() {
  const router = useRouter();
  const { code, pair } = useLocalSearchParams<{ code: string; pair?: string }>();

  // If a pair param exists, the user arrived from a choose-one slot
  const pairOptions = pair ? [code ?? "", pair] : null;
  const [selectedCode, setSelectedCode] = useState<string>(code ?? "");

  const [detail, setDetail]               = useState<CourseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);

  // Reload detail whenever selectedCode changes
  useEffect(() => {
    if (!selectedCode) return;
    setDetail(null);
    setDetailLoading(true);

    getCourseDetail(selectedCode)
      .then(setDetail)
      .catch(() => {})
      .finally(() => setDetailLoading(false));
  }, [selectedCode]);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#fff" }} edges={["top", "left", "right"]}>

      {/* ── Header ── */}
      <View style={{
        flexDirection: "row", alignItems: "center",
        paddingHorizontal: 16, paddingVertical: 14,
        borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
      }}>
        <TouchableOpacity
          onPress={() => router.back()}
          hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
          style={{
            width: 36, height: 36, borderRadius: 18,
            backgroundColor: "#f3f4f6",
            alignItems: "center", justifyContent: "center",
            marginRight: 12,
          }}
        >
          <Text style={{ fontSize: 18, color: "#1a3a6b", fontWeight: "600", marginTop: -1 }}>←</Text>
        </TouchableOpacity>
        <Text style={{ fontSize: 18, fontWeight: "700", color: "#1a3a6b", flex: 1 }}>
          {selectedCode}
        </Text>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 20, paddingBottom: 48 }}
        showsVerticalScrollIndicator={false}
      >
        {/* Course switcher — only shown for choose-one pairs */}
        {pairOptions && (
          <View style={{ flexDirection: "row", gap: 8, marginBottom: 20 }}>
            {pairOptions.map((opt) => {
              const active = opt === selectedCode;
              return (
                <TouchableOpacity
                  key={opt}
                  onPress={() => setSelectedCode(opt)}
                  style={{
                    paddingHorizontal: 16, paddingVertical: 8,
                    borderRadius: 20,
                    backgroundColor: active ? "#1a3a6b" : "#f3f4f6",
                    borderWidth: 1,
                    borderColor: active ? "#1a3a6b" : "#e5e7eb",
                  }}
                >
                  <Text style={{
                    fontSize: 13, fontWeight: "700",
                    color: active ? "#fff" : "#6b7280",
                  }}>
                    {opt}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        )}

        {/* ── Course info ── */}
        {detailLoading ? (
          <ActivityIndicator color="#1a3a6b" style={{ marginVertical: 16 }} />
        ) : detail ? (
          <View>
            {detail.course_title ? (
              <Text style={{ fontSize: 20, fontWeight: "800", color: "#1a3a6b", marginBottom: 10 }}>
                {detail.course_title}
              </Text>
            ) : null}
            {detail.credits > 0 && (
              <View style={{ flexDirection: "row", marginBottom: detail.description ? 12 : 0 }}>
                <View style={{ backgroundColor: "#dbeafe", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 }}>
                  <Text style={{ fontSize: 12, fontWeight: "700", color: "#1a3a6b" }}>
                    {/* credits_label carries "1.5-3" for variable-credit courses;
                        older backends send only the number. */}
                    {detail.credits_label ?? detail.credits} credits
                  </Text>
                </View>
              </View>
            )}
            {detail.description ? (
              <CourseDescription text={detail.description} />
            ) : null}
          </View>
        ) : (
          <Text style={{ fontSize: 13, color: "#9ca3af" }}>
            Couldn't load details for {selectedCode}.
          </Text>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
