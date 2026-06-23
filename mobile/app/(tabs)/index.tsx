import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import axios from "axios";
import { API_BASE, USER_ID } from "../../constants/api";
import { NavHeader } from "../../components/NavHeader";

// ── Types ─────────────────────────────────────────────────────────────────────

type TimelineCourse = {
  course_code: string;
  course_title?: string;
  grade: string;
  credits_earned: number;
  status: "done" | "in_progress" | "missing";
  is_pool?: boolean;
};

type Semester = {
  term: string;
  label: string;
  status: "completed" | "current" | "upcoming";
  credits: number;
  courses: TimelineCourse[];
};

type TimelineData = {
  major: string;
  subplan: string | null;
  transcript_credits: number;
  semesters: Semester[];
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function shortTerm(label: string): { season: string; year: string } {
  const parts = label.split(" ");
  if (parts.length < 2) return { season: label, year: "" };
  const abbr: Record<string, string> = {
    Spring: "SP", Summer: "SU", Fall: "FA",
  };
  return { season: abbr[parts[0]] ?? parts[0], year: `'${parts[1].slice(2)}` };
}

// ── Timeline node ─────────────────────────────────────────────────────────────

function TimelineNode({
  semester,
  selected,
  onPress,
  isLast,
}: {
  semester: Semester;
  selected: boolean;
  onPress: () => void;
  isLast: boolean;
}) {
  const { season, year } = shortTerm(semester.label);
  const isCompleted = semester.status === "completed";
  const isCurrent   = semester.status === "current";

  return (
    <View className="flex-row items-center">
      {/* Node */}
      <TouchableOpacity
        onPress={onPress}
        activeOpacity={0.7}
        className="items-center"
        style={{ width: 56 }}
      >
        {/* Outer ring when selected */}
        <View
          className={`items-center justify-center rounded-full ${
            selected ? "w-8 h-8 bg-navy" : "w-6 h-6"
          }`}
        >
          <View
            className={`rounded-full ${
              selected
                ? "w-3.5 h-3.5 bg-white"
                : isCompleted || isCurrent
                ? "w-3.5 h-3.5 bg-navy"
                : "w-3 h-3 border-2 border-gray-300 bg-white"
            }`}
          />
        </View>

        {/* Labels */}
        <Text
          className={`text-xs font-bold mt-1.5 ${
            selected ? "text-navy" : isCompleted || isCurrent ? "text-gray-700" : "text-gray-400"
          }`}
        >
          {season}
        </Text>
        <Text
          className={`text-xs ${
            selected ? "text-navy-mid" : "text-gray-400"
          }`}
        >
          {year}
        </Text>
      </TouchableOpacity>

      {/* Connector line to next node */}
      {!isLast && (
        <View
          className="h-px"
          style={{ width: 16, backgroundColor: "#e5e7eb" }}
        />
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

function ContentPanel({ semester }: { semester: Semester }) {
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

      {/* Course list */}
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
        showsVerticalScrollIndicator={false}
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

  const fetchTimeline = useCallback(async () => {
    try {
      const res = await axios.get<TimelineData>(`${API_BASE}/timeline`, {
        headers: { "x-user-id": USER_ID },
      });
      setData(res.data);
      setError(null);
      // Auto-select current semester, or last completed if no current
      const cur = res.data.semesters.find((s) => s.status === "current");
      const last = res.data.semesters.filter((s) => s.status === "completed").at(-1);
      setSelectedTerm(cur?.term ?? last?.term ?? res.data.semesters[0]?.term ?? null);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "Could not load timeline. Is the backend running?");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchTimeline(); }, [fetchTimeline]);
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

  const creditPct       = Math.min(100, Math.round((data.transcript_credits / 120) * 100));
  const selectedSemester = data.semesters.find((s) => s.term === selectedTerm);

  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top","left","right"]}>
      <ScrollView
        className="flex-1"
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#1a3a6b" />}
        scrollEnabled={false}
        contentContainerStyle={{ flex: 1 }}
      >
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
            contentContainerStyle={{ paddingHorizontal: 20, paddingVertical: 20, alignItems: "center" }}
          >
            {data.semesters.map((sem, i) => (
              <TimelineNode
                key={sem.term}
                semester={sem}
                selected={sem.term === selectedTerm}
                onPress={() => setSelectedTerm(sem.term)}
                isLast={i === data.semesters.length - 1}
              />
            ))}
          </ScrollView>
        </View>

        {/* Content area */}
        {selectedSemester ? (
          <ContentPanel semester={selectedSemester} />
        ) : (
          <View className="flex-1 items-center justify-center">
            <Text className="text-gray-300">Select a semester above</Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
