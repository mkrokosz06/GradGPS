import React, { useState, useCallback } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { NavHeader } from "../../components/NavHeader";
import { useAuth } from "../../context/AuthContext";
import { getTimeline, type TimelineCourse, type Semester, type TimelineData } from "../../services/timelineService";

// ── Helpers ───────────────────────────────────────────────────────────────────

const CLASS_YEAR_LABELS = ["Freshman", "Sophomore", "Junior", "Senior"];

function getAcademicYearIndex(term: string, firstFaYear: number): number {
  const [season, yearStr] = term.split(" ");
  const year = parseInt(yearStr, 10);
  if (season === "FA") return year - firstFaYear + 1;
  if (season === "SP") return year - firstFaYear;
  return year - firstFaYear; // SU — treated same as preceding year
}

function classYearLabel(idx: number): string | null {
  if (idx <= 0) return null;
  return CLASS_YEAR_LABELS[idx - 1] ?? `Year ${idx}`;
}

// ── Map pin ───────────────────────────────────────────────────────────────────

function MapPin() {
  const COLOR = "#E8C84B";  // gold
  return (
    <View style={{ alignItems: "center" }}>
      {/* Circle head */}
      <View style={{
        width: 22, height: 22, borderRadius: 11,
        backgroundColor: COLOR,
        alignItems: "center", justifyContent: "center",
        shadowColor: COLOR, shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.5, shadowRadius: 4, elevation: 4,
      }}>
        {/* Inner dot */}
        <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: "#1a3a6b" }} />
      </View>
      {/* Downward point (CSS triangle trick) */}
      <View style={{
        width: 0, height: 0,
        borderLeftWidth: 6,  borderLeftColor:  "transparent",
        borderRightWidth: 6, borderRightColor: "transparent",
        borderTopWidth: 9,   borderTopColor:   COLOR,
        marginTop: -1,
      }} />
    </View>
  );
}

// ── Timeline node ─────────────────────────────────────────────────────────────

// Fixed geometry so the connector line can be precisely aligned to circle center.
const LABEL_H    = 34;  // reserved height for year-label / pin row
const LABEL_MB   = 6;   // margin below that row before circle container
const CIRCLE_BOX = 32;  // fixed-size container wrapping the circle
// Circle center Y from the top of the node = LABEL_H + LABEL_MB + CIRCLE_BOX/2
const CIRCLE_CENTER_Y = LABEL_H + LABEL_MB + CIRCLE_BOX / 2; // 56

function TimelineNode({
  semester,
  selected,
  onPress,
  isLast,
  yearLabel,
  lineColor,
}: {
  semester: Semester;
  selected: boolean;
  onPress: () => void;
  isLast: boolean;
  yearLabel: string | null;
  lineColor: string;
}) {
  const parts       = semester.label.split(" ");  // ["Fall", "2025"]
  const season      = parts[0] ?? "";
  const year        = parts[1] ?? "";
  const isCompleted = semester.status === "completed";
  const isCurrent   = semester.status === "current";

  const circleSize   = selected ? 28 : 20;
  const circleBg     = isCurrent  ? "#E8C84B"
                     : (isCompleted || selected) ? "#1a3a6b"
                     : "transparent";
  const circleBorder = isCurrent  ? "#E8C84B"
                     : (isCompleted || selected) ? "#1a3a6b"
                     : "#d1d5db";
  const textColor    = selected ? "#1a3a6b" : (isCompleted || isCurrent) ? "#374151" : "#9ca3af";

  const LINE_H = 3;

  return (
    // alignItems: "flex-start" so marginTop on the line is relative to the top of the row
    <View style={{ flexDirection: "row", alignItems: "flex-start" }}>
      {/* Node column */}
      <TouchableOpacity
        onPress={onPress}
        activeOpacity={0.7}
        style={{ alignItems: "center", width: 88 }}
      >
        {/* Label row — fixed height keeps all circles aligned.
            Current semester shows a gold map pin; others show year label text. */}
        <View style={{ height: LABEL_H, justifyContent: "flex-end", alignItems: "center", marginBottom: LABEL_MB }}>
          {isCurrent ? (
            <MapPin />
          ) : yearLabel ? (
            <Text style={{
              color: "#1a3a6b", fontSize: 10, fontWeight: "800",
              letterSpacing: 0.7, textTransform: "uppercase",
            }}>
              {yearLabel}
            </Text>
          ) : null}
        </View>

        {/* Fixed-size box so circle center Y is constant regardless of selection state */}
        <View style={{ width: CIRCLE_BOX, height: CIRCLE_BOX, alignItems: "center", justifyContent: "center" }}>
          <View style={{
            width: circleSize, height: circleSize, borderRadius: circleSize / 2,
            backgroundColor: circleBg,
            borderWidth: 2.5, borderColor: circleBorder,
            alignItems: "center", justifyContent: "center",
          }}>
            {selected && (
              <View style={{ width: 9, height: 9, borderRadius: 4.5, backgroundColor: "#ffffff" }} />
            )}
          </View>
        </View>

        <Text style={{ marginTop: 7, fontSize: 13, fontWeight: "600", color: textColor }}>
          {season}
        </Text>
        <Text style={{ fontSize: 12, color: selected ? "#2a5298" : "#9ca3af", marginTop: 1 }}>
          {year}
        </Text>
      </TouchableOpacity>

      {/* Connector line — marginTop positions it exactly at circle center */}
      {!isLast && (
        <View style={{
          width: 28,
          height: LINE_H,
          backgroundColor: lineColor,
          borderRadius: LINE_H / 2,
          marginTop: CIRCLE_CENTER_Y - LINE_H / 2,
        }} />
      )}
    </View>
  );
}

// ── Course row ────────────────────────────────────────────────────────────────

function CourseRow({ course }: { course: TimelineCourse }) {
  const config = {
    done:        { dot: "✓", dotColor: "text-done",     textColor: "text-gray-800", bg: "bg-green-50" },
    in_progress: { dot: "→", dotColor: "text-progress", textColor: "text-gray-800", bg: "bg-amber-50" },
    missing:     { dot: "○", dotColor: "text-gray-300", textColor: "text-gray-400", bg: "bg-white" },
  }[course.status] ?? { dot: "○", dotColor: "text-gray-300", textColor: "text-gray-400", bg: "bg-white" };

  return (
    <View className={`flex-row items-center px-4 py-3 mb-1.5 rounded-xl border border-gray-100 ${config.bg}`}>
      <Text className={`w-5 text-center text-sm font-bold ${config.dotColor}`}>{config.dot}</Text>
      <View className="flex-1 ml-3">
        <Text className={`text-sm font-semibold ${config.textColor}`}>{course.course_code}</Text>
        {course.course_title ? (
          <Text className="text-gray-400 text-xs mt-0.5" numberOfLines={1}>{course.course_title}</Text>
        ) : null}
      </View>
      <View className="ml-3 items-end">
        {course.grade ? (
          <Text className="text-gray-600 text-sm font-bold">{course.grade}</Text>
        ) : course.credits_earned > 0 ? (
          <Text className="text-gray-400 text-xs">{course.credits_earned} cr</Text>
        ) : null}
      </View>
    </View>
  );
}

// ── Content panel ─────────────────────────────────────────────────────────────

function ContentPanel({
  semester,
  refreshing,
  onRefresh,
}: {
  semester: Semester;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const isCompleted = semester.status === "completed";
  const isCurrent   = semester.status === "current";
  const isUpcoming  = semester.status === "upcoming";

  const statusLabel = isCurrent
    ? "In Progress"
    : isUpcoming
    ? "Recommended"
    : `${semester.credits} credits earned`;

  const statusColor = isCurrent ? "text-progress" : isUpcoming ? "text-gray-400" : "text-done";

  return (
    <View className="flex-1">
      {/* Panel header */}
      <View className="px-5 pt-4 pb-3 border-b border-gray-100 flex-row items-center justify-between">
        <View>
          <Text className="text-navy font-bold text-lg">{semester.label}</Text>
          <Text className={`text-xs font-semibold mt-0.5 ${statusColor}`}>{statusLabel}</Text>
        </View>
        {isUpcoming && (
          <View className="bg-gray-100 px-3 py-1 rounded-full">
            <Text className="text-gray-400 text-xs font-semibold">~{semester.credits} cr</Text>
          </View>
        )}
      </View>

      {/* Course list — RefreshControl lives here so pull-to-refresh works */}
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#1a3a6b" />
        }
      >
        {semester.courses.length === 0 ? (
          <Text className="text-gray-300 text-center mt-6">No courses recorded</Text>
        ) : (
          semester.courses.map((c, i) => (
            <CourseRow key={`${c.course_code}_${i}`} course={c} />
          ))
        )}
      </ScrollView>
    </View>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export default function TimelineScreen() {
  const [data, setData]             = useState<TimelineData | null>(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);
  const { userId } = useAuth();

  const fetchTimeline = useCallback(async () => {
    if (!userId) { setLoading(false); return; }
    try {
      const timeline = await getTimeline(userId);
      setData(timeline);
      setError(null);
      // Auto-select current semester, or last completed if no current
      const cur  = timeline.semesters.find((s) => s.status === "current");
      const last = timeline.semesters.filter((s) => s.status === "completed").at(-1);
      setSelectedTerm(cur?.term ?? last?.term ?? timeline.semesters[0]?.term ?? null);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not load timeline. Is the backend running?");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [userId]);

  // Re-fetch every time this screen comes into focus (e.g. after upload or major change)
  useFocusEffect(useCallback(() => { fetchTimeline(); }, [fetchTimeline]));
  const onRefresh = useCallback(() => { setRefreshing(true); fetchTimeline(); }, [fetchTimeline]);

  // ── Loading ──────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <SafeAreaView className="flex-1 bg-white items-center justify-center" edges={["top","left","right"]}>
        <ActivityIndicator size="large" color="#1a3a6b" />
        <Text className="text-gray-400 mt-3 text-sm">Loading timeline…</Text>
      </SafeAreaView>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <SafeAreaView className="flex-1 bg-white" edges={["top","left","right"]}>
        <NavHeader />
        <View className="flex-1 items-center justify-center px-8">
          <Text className="text-gray-800 text-center font-semibold mb-6">{error}</Text>
          <TouchableOpacity
            onPress={fetchTimeline}
            className="bg-navy px-6 py-3 rounded-xl"
          >
            <Text className="text-white font-bold">Retry</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  if (!data) return null;

  const creditPct        = Math.min(100, Math.round((data.transcript_credits / 120) * 100));
  const selectedSemester = data.semesters.find((s) => s.term === selectedTerm);

  // Compute academic year labels (Freshman / Sophomore / …)
  const firstFaYear = data.semesters
    .filter((s) => s.term.startsWith("FA"))
    .reduce((min, s) => Math.min(min, parseInt(s.term.split(" ")[1], 10)), Infinity);

  let prevYearIdx = -1;
  const semestersWithLabel = data.semesters.map((sem) => {
    const idx = firstFaYear === Infinity ? 0 : getAcademicYearIndex(sem.term, firstFaYear);
    const label = idx !== prevYearIdx ? classYearLabel(idx) : null;
    prevYearIdx = idx;
    return { sem, yearLabel: label };
  });

  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top","left","right"]}>
      <View className="flex-1">
        {/* Header */}
        <NavHeader subtitle={data.major} />

        {/* Credit progress strip */}
        <View className="px-5 pt-4 pb-3 bg-white border-b border-gray-100">
          <View className="flex-row items-end justify-between mb-2">
            <View>
              <Text className="text-navy font-bold text-2xl">{data.transcript_credits}</Text>
              <Text className="text-gray-400 text-xs">credits earned</Text>
            </View>
            <Text className="text-gray-400 text-xs mb-1">{creditPct}% of 120</Text>
            <View className="items-end">
              <Text className="text-gray-500 font-bold text-2xl">{120 - data.transcript_credits}</Text>
              <Text className="text-gray-400 text-xs">remaining</Text>
            </View>
          </View>
          {/* Progress bar */}
          <View className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <View
              className="h-full bg-navy rounded-full"
              style={{ width: `${creditPct}%` }}
            />
          </View>
        </View>

        {/* Horizontal timeline */}
        <View className="border-b border-gray-100 bg-white">
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: 24, paddingTop: 12, paddingBottom: 20, alignItems: "center" }}
          >
            {semestersWithLabel.map(({ sem, yearLabel }, i) => (
              <TimelineNode
                key={sem.term}
                semester={sem}
                selected={sem.term === selectedTerm}
                onPress={() => setSelectedTerm(sem.term)}
                isLast={i === semestersWithLabel.length - 1}
                yearLabel={yearLabel}
                lineColor={
                  sem.status === "completed" ? "#1a3a6b"
                  : sem.status === "current"  ? "#E8C84B"
                  : "#e5e7eb"
                }
              />
            ))}
          </ScrollView>
        </View>

        {/* Content area */}
        {selectedSemester ? (
          <ContentPanel semester={selectedSemester} refreshing={refreshing} onRefresh={onRefresh} />
        ) : (
          <View className="flex-1 items-center justify-center">
            <Text className="text-gray-300">Select a semester above</Text>
          </View>
        )}
      </View>
    </SafeAreaView>
  );
}
