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
import { useFocusEffect, useRouter } from "expo-router";
import { NavHeader } from "../../components/NavHeader";
import { useAuth } from "../../context/AuthContext";
import { getTimeline, type TimelineCourse, type Semester, type TimelineData } from "../../services/timelineService";

// ── Helpers ───────────────────────────────────────────────────────────────────

function getAcademicYearIndex(term: string, firstFaYear: number): number {
  if (term === "Transfer") return -1;
  const [season, yearStr] = term.split(" ");
  const year = parseInt(yearStr, 10);
  if (season === "FA") return year - firstFaYear + 1;
  if (season === "SP") return year - firstFaYear;
  return year - firstFaYear;
}

// ── Bracket types & helpers ───────────────────────────────────────────────────

type BracketRole = "start" | "middle" | "end" | "single" | "none";

interface BracketInfo {
  role:        BracketRole;
  label:       string;   // set only on start/single
  spanWidthPx: number;   // pixel width of full bracket (start/single only)
}

const BRACKET_LINE_H  = 2;
const BRACKET_TICK_H  = 12;
const BRACKET_LABEL_H = 14;
const BRACKET_CELL_H  = BRACKET_LABEL_H + BRACKET_LINE_H + BRACKET_TICK_H; // 28 px

function getBracketLabel(idx: number): string {
  if (idx === 1) return "Freshman";
  if (idx === 2) return "Sophomore";
  if (idx === 3) return "Junior";
  if (idx === 4) return "Senior";
  if (idx >= 5)  return `${idx}th Year`;
  return "";
}

function computeBracketInfo(semesters: Semester[], firstFaYear: number): BracketInfo[] {
  const result: BracketInfo[] = semesters.map(() => ({ role: "none", label: "", spanWidthPx: 0 }));

  // Group FA/SP semesters by academic year index (Transfer + SU excluded)
  const yearGroups = new Map<number, number[]>(); // yearIdx → [semesterIndex, ...]
  for (let i = 0; i < semesters.length; i++) {
    const sem = semesters[i];
    if (sem.term === "Transfer") continue;
    const season = sem.term.split(" ")[0];
    if (season === "SU") continue;
    const idx = firstFaYear === Infinity ? 0 : getAcademicYearIndex(sem.term, firstFaYear);
    if (idx <= 0) continue;
    const group = yearGroups.get(idx) ?? [];
    group.push(i);
    yearGroups.set(idx, group);
  }

  for (const [idx, positions] of yearGroups) {
    const label        = getBracketLabel(idx);
    const n            = positions.length;
    // span in px: from center of first node to center of last node
    const spanWidthPx  = (positions[n - 1] - positions[0]) * NODE_TOTAL;

    if (n === 1) {
      result[positions[0]] = { role: "single", label, spanWidthPx: 0 };
    } else {
      result[positions[0]]     = { role: "start",  label, spanWidthPx };
      for (let i = 1; i < n - 1; i++) {
        result[positions[i]]   = { role: "middle", label: "", spanWidthPx: 0 };
      }
      result[positions[n - 1]] = { role: "end",    label: "", spanWidthPx: 0 };
    }
  }

  return result;
}

// ── Bracket cell ──────────────────────────────────────────────────────────────

function BracketCell({ info }: { info: BracketInfo }) {
  const { role, label, spanWidthPx } = info;
  if (role === "none") return <View style={{ width: NODE_TOTAL, height: BRACKET_CELL_H }} />;

  const centerX   = NODE_W / 2;   // 44 px — center of node within slot
  const lineColor = "#cbd5e1";

  // Horizontal line sits just below the label; ticks hang DOWN from it
  const lineTop = BRACKET_LABEL_H;
  // Ticks start AT the same Y as the line so they overlap → no seam at corner
  const tickTop = BRACKET_LABEL_H;

  // Horizontal line left/right bounds.
  // For end/single: extend the line UNDER the tick (centerX → centerX + LINE_H)
  // so the corner pixel is always covered.
  const lineLeft  = (role === "end"   || role === "middle") ? 0
                  : centerX;
  const lineRight = (role === "start" || role === "middle") ? 0
                  : (role === "end")    ? NODE_TOTAL - centerX - BRACKET_LINE_H
                  : NODE_TOTAL - centerX;  // single: zero-width (just the tick)

  return (
    <View style={{ width: NODE_TOTAL, height: BRACKET_CELL_H }}>
      {/* Year label — centered over full bracket span, or over the tick for single */}
      {label ? (
        <Text
          numberOfLines={1}
          style={{
            position:      "absolute",
            left:          role === "single" ? centerX - 40 : centerX,
            width:         role === "single" ? 80 : Math.max(spanWidthPx, 70),
            top:           0,
            textAlign:     "center",
            fontSize:      10,
            fontWeight:    "700",
            color:         "#94a3b8",
            letterSpacing: 0.8,
            textTransform: "uppercase",
          }}
        >
          {label}
        </Text>
      ) : null}

      {/* Horizontal bracket line */}
      <View style={{
        position:        "absolute",
        left:            lineLeft,
        right:           lineRight,
        top:             lineTop,
        height:          BRACKET_LINE_H,
        backgroundColor: lineColor,
      }} />

      {/* Left cap — overlaps line top so corner is seamless (start / single) */}
      {(role === "start" || role === "single") && (
        <View style={{
          position:        "absolute",
          left:            centerX,
          top:             tickTop,
          width:           BRACKET_LINE_H,
          height:          BRACKET_LINE_H + BRACKET_TICK_H,
          backgroundColor: lineColor,
        }} />
      )}

      {/* Right cap — overlaps line top so corner is seamless (end / single) */}
      {(role === "end" || role === "single") && (
        <View style={{
          position:        "absolute",
          left:            centerX,
          top:             tickTop,
          width:           BRACKET_LINE_H,
          height:          BRACKET_LINE_H + BRACKET_TICK_H,
          backgroundColor: lineColor,
        }} />
      )}
    </View>
  );
}

// ── Map pin ───────────────────────────────────────────────────────────────────

function MapPin() {
  const COLOR = "#E8C84B";
  return (
    <View style={{ alignItems: "center" }}>
      <View style={{
        width: 22, height: 22, borderRadius: 11,
        backgroundColor: COLOR,
        alignItems: "center", justifyContent: "center",
        shadowColor: COLOR, shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.5, shadowRadius: 4, elevation: 4,
      }}>
        <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: "#1a3a6b" }} />
      </View>
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

const NODE_W      = 88;
const CONNECTOR_W = 28;
const NODE_TOTAL  = NODE_W + CONNECTOR_W; // 116 px per slot

const LABEL_H        = 34;
const LABEL_MB       = 6;
const CIRCLE_BOX     = 32;
const CIRCLE_CENTER_Y = LABEL_H + LABEL_MB + CIRCLE_BOX / 2; // 56

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
  const isTransfer  = semester.term === "Transfer";
  const parts       = semester.label.split(" ");
  const season      = isTransfer ? "XFER" : (parts[0] ?? "");
  const year        = isTransfer ? ""     : (parts[1] ?? "");
  const isCompleted = semester.status === "completed";
  const isCurrent   = semester.status === "current";
  const isUpcoming  = semester.status === "upcoming";

  const circleSize = selected ? 28 : 20;

  // Completed → navy fill; Current → gold; Upcoming → white with navy border; Selected → navy
  const circleBg =
    isCurrent   ? "#E8C84B" :
    isUpcoming  ? "#ffffff" :
    (isCompleted || selected) ? "#1a3a6b" :
    "#ffffff";

  const circleBorder =
    isCurrent   ? "#E8C84B" :
    isUpcoming  ? "#1a3a6b" :
    (isCompleted || selected) ? "#1a3a6b" :
    "#d1d5db";

  const textColor = selected ? "#1a3a6b" : (isCompleted || isCurrent) ? "#374151" : "#1a3a6b";

  const lineColor =
    isCompleted ? "#1a3a6b" :
    isCurrent   ? "#E8C84B" :
    "#1a3a6b";   // upcoming connector also navy so it's visible

  const LINE_H = 3;

  return (
    <View style={{ flexDirection: "row", alignItems: "flex-start" }}>
      <TouchableOpacity
        onPress={onPress}
        activeOpacity={0.7}
        style={{ alignItems: "center", width: NODE_W }}
      >
        <View style={{ height: LABEL_H, justifyContent: "flex-end", alignItems: "center", marginBottom: LABEL_MB }}>
          {isCurrent ? <MapPin /> : null}
        </View>

        <View style={{ width: CIRCLE_BOX, height: CIRCLE_BOX, alignItems: "center", justifyContent: "center" }}>
          <View style={{
            width: circleSize, height: circleSize, borderRadius: circleSize / 2,
            backgroundColor: circleBg,
            borderWidth: 2.5, borderColor: circleBorder,
            alignItems: "center", justifyContent: "center",
          }}>
            {selected && (
              <View style={{ width: 9, height: 9, borderRadius: 4.5, backgroundColor: isUpcoming ? "#1a3a6b" : "#ffffff" }} />
            )}
          </View>
        </View>

        <Text style={{ marginTop: 7, fontSize: 13, fontWeight: "600", color: textColor }}>
          {season}
        </Text>
        <Text style={{ fontSize: 12, color: selected ? "#2a5298" : isUpcoming ? "#1a3a6b" : "#9ca3af", marginTop: 1 }}>
          {year}
        </Text>
      </TouchableOpacity>

      {!isLast && (
        <View style={{
          width: CONNECTOR_W,
          height: LINE_H,
          backgroundColor: lineColor,
          borderRadius: LINE_H / 2,
          marginTop: CIRCLE_CENTER_Y - LINE_H / 2,
          opacity: isUpcoming ? 0.3 : 1,
        }} />
      )}
    </View>
  );
}

// ── Pool dropdown row ─────────────────────────────────────────────────────────

function PoolDropdownRow({ course }: { course: TimelineCourse }) {
  const [expanded, setExpanded] = useState(false);
  const poolCourses = course.pool_courses ?? [];
  const needed      = course.pool_needed_credits ?? course.pool_needed_courses ?? 0;
  const unit        = course.pool_needed_credits != null ? "cr" : "courses";

  return (
    <View className="mb-1.5">
      <TouchableOpacity
        onPress={() => setExpanded(e => !e)}
        activeOpacity={0.7}
        style={{
          flexDirection: "row", alignItems: "center",
          paddingHorizontal: 16, paddingVertical: 12,
          backgroundColor: "#f8fafc",
          borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0",
        }}
      >
        <Text style={{ fontSize: 13, color: "#94a3b8", marginRight: 10 }}>
          {expanded ? "▾" : "▸"}
        </Text>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 13, fontWeight: "600", color: "#374151" }}>
            Elective Pool — Pick {needed} {unit}
          </Text>
          <Text style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }} numberOfLines={1}>
            {course.course_code}
          </Text>
        </View>
        <Text style={{ fontSize: 11, color: "#cbd5e1" }}>{poolCourses.length} options</Text>
      </TouchableOpacity>

      {expanded && (
        <View style={{
          marginTop: 2, marginLeft: 12,
          borderLeftWidth: 2, borderLeftColor: "#e2e8f0",
          paddingLeft: 12,
        }}>
          {poolCourses.map((c, i) => (
            <View
              key={i}
              style={{
                flexDirection: "row", alignItems: "center",
                paddingVertical: 8,
                borderBottomWidth: i < poolCourses.length - 1 ? 1 : 0,
                borderBottomColor: "#f1f5f9",
              }}
            >
              <Text style={{ color: "#cbd5e1", fontSize: 14, marginRight: 8 }}>◦</Text>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 13, fontWeight: "600", color: "#475569" }}>
                  {c.course_code}
                </Text>
                {c.course_title ? (
                  <Text style={{ fontSize: 11, color: "#94a3b8", marginTop: 1 }} numberOfLines={1}>
                    {c.course_title}
                  </Text>
                ) : null}
              </View>
              <Text style={{ fontSize: 11, color: "#94a3b8", marginLeft: 8 }}>{c.credits} cr</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

// ── Course row ────────────────────────────────────────────────────────────────

function CourseRow({ course }: { course: TimelineCourse }) {
  const router = useRouter();
  const config = {
    done:        { dot: "✓", dotColor: "text-done",     textColor: "text-gray-800", bg: "bg-green-50" },
    in_progress: { dot: "→", dotColor: "text-progress", textColor: "text-gray-800", bg: "bg-amber-50" },
    missing:     { dot: "○", dotColor: "text-gray-300", textColor: "text-gray-400", bg: "bg-white" },
  }[course.status] ?? { dot: "○", dotColor: "text-gray-300", textColor: "text-gray-400", bg: "bg-white" };

  // Pool entries
  if (course.is_pool) {
    // Small named pool (e.g. option-specific courses) → expandable dropdown
    if (course.pool_courses && course.pool_courses.length > 0) {
      return <PoolDropdownRow course={course} />;
    }

    // Gen Ed multi-category or large pool summary → flat display
    const cats = course.gen_ed_categories;
    return (
      <View className={`flex-row items-start px-4 py-3 mb-1.5 rounded-xl border border-gray-100 ${config.bg}`}>
        <Text className={`w-5 text-center text-sm font-bold mt-0.5 ${config.dotColor}`}>{config.dot}</Text>
        <View className="flex-1 ml-3">
          <Text className={`text-sm font-semibold ${config.textColor}`}>
            {cats && cats.length > 0 ? "Elective" : course.course_code}
          </Text>
          {cats && cats.map((cat, i) => (
            <Text key={i} className="text-gray-400 text-xs mt-0.5">{cat}</Text>
          ))}
          {!cats && course.course_title ? (
            <Text className="text-gray-400 text-xs mt-0.5">{course.course_title}</Text>
          ) : null}
        </View>
      </View>
    );
  }

  const pairCodes = course.course_code.includes(" or ")
    ? course.course_code.split(" or ").map((s) => s.trim())
    : null;

  const handlePress = () => {
    if (pairCodes) {
      router.push(`/course/${encodeURIComponent(pairCodes[0])}?pair=${encodeURIComponent(pairCodes[1])}` as any);
    } else {
      router.push(`/course/${encodeURIComponent(course.course_code)}` as any);
    }
  };

  return (
    <TouchableOpacity
      activeOpacity={0.7}
      onPress={handlePress}
      className={`flex-row items-center px-4 py-3 mb-1.5 rounded-xl border border-gray-100 ${config.bg}`}
    >
      <Text className={`w-5 text-center text-sm font-bold ${config.dotColor}`}>{config.dot}</Text>
      <View className="flex-1 ml-3">
        <Text className={`text-sm font-semibold ${config.textColor}`}>{course.course_code}</Text>
        {course.course_title ? (
          <Text className="text-gray-400 text-xs mt-0.5" numberOfLines={1}>{course.course_title}</Text>
        ) : null}
        <Text className="text-gray-400 text-xs mt-0.5">tap for ratings ›</Text>
      </View>
      <View className="ml-3 items-end">
        {course.grade ? (
          <Text className="text-gray-600 text-sm font-bold">{course.grade}</Text>
        ) : course.credits_earned > 0 ? (
          <Text className="text-gray-400 text-xs">{course.credits_earned} cr</Text>
        ) : null}
      </View>
    </TouchableOpacity>
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
  const isCurrent  = semester.status === "current";
  const isUpcoming = semester.status === "upcoming";

  const statusLabel = isCurrent
    ? "In Progress"
    : isUpcoming
    ? "Recommended"
    : `${semester.credits} credits earned`;

  const statusColor = isCurrent ? "text-progress" : isUpcoming ? "text-navy" : "text-done";

  return (
    <View className="flex-1">
      <View className="px-5 pt-4 pb-3 border-b border-gray-100 flex-row items-center justify-between">
        <View>
          <Text className="text-navy font-bold text-lg">{semester.label}</Text>
          <Text className={`text-xs font-semibold mt-0.5 ${statusColor}`}>{statusLabel}</Text>
        </View>
        {isUpcoming && (
          <View className="bg-blue-50 px-3 py-1 rounded-full border border-blue-100">
            <Text className="text-navy text-xs font-semibold">~{semester.credits} cr</Text>
          </View>
        )}
      </View>

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
  const timelineScrollRef = useRef<ScrollView>(null);

  const fetchTimeline = useCallback(async () => {
    if (!userId) { setLoading(false); return; }
    try {
      const timeline = await getTimeline(userId);
      setData(prev => {
        const isFirstLoad = prev === null;

        // Auto-select term: current → last completed → first semester
        const cur  = timeline.semesters.find((s) => s.status === "current");
        const last = timeline.semesters.filter((s) => s.status === "completed").at(-1);
        const defaultTerm = cur?.term ?? last?.term ?? timeline.semesters[0]?.term ?? null;

        setSelectedTerm(existing => {
          // Keep the user's selection if it still exists in the refreshed data
          if (existing && timeline.semesters.some((s) => s.term === existing)) return existing;
          return defaultTerm;
        });

        // Only auto-scroll on first load
        if (isFirstLoad && defaultTerm) {
          const idx = timeline.semesters.findIndex((s) => s.term === defaultTerm);
          if (idx > 2) {
            setTimeout(() => {
              timelineScrollRef.current?.scrollTo({
                x: Math.max(0, (idx - 1) * NODE_TOTAL),
                animated: true,
              });
            }, 300);
          }
        }

        return timeline;
      });
      setError(null);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not load timeline. Is the backend running?");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [userId]);

  // Fetch on mount and whenever userId changes (handles async AsyncStorage load)
  useEffect(() => { fetchTimeline(); }, [fetchTimeline]);
  // Re-fetch whenever this screen gains focus (after upload, major change, etc.)
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
          <TouchableOpacity onPress={fetchTimeline} className="bg-navy px-6 py-3 rounded-xl">
            <Text className="text-white font-bold">Retry</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  if (!data) return null;

  const creditPct        = Math.min(100, Math.round((data.transcript_credits / 120) * 100));
  const selectedSemester = data.semesters.find((s) => s.term === selectedTerm);

  const firstFaYear = data.semesters
    .filter((s) => s.term.startsWith("FA"))
    .reduce((min, s) => Math.min(min, parseInt(s.term.split(" ")[1], 10)), Infinity);

  const bracketInfos = computeBracketInfo(data.semesters, firstFaYear);

  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top","left","right"]}>
      <View className="flex-1">
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
              <Text className="text-navy font-bold text-2xl">{120 - data.transcript_credits}</Text>
              <Text className="text-gray-400 text-xs">remaining</Text>
            </View>
          </View>
          <View className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <View className="h-full bg-navy rounded-full" style={{ width: `${creditPct}%` }} />
          </View>
        </View>

        {/* Horizontal timeline */}
        <View className="border-b border-gray-100 bg-white">
          <ScrollView
            ref={timelineScrollRef}
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: 24, paddingTop: 10, paddingBottom: 8 }}
          >
            <View>
              {/* Bracket row — year grouping brackets above the dots */}
              <View style={{ flexDirection: "row" }}>
                {data.semesters.map((sem, i) => (
                  <BracketCell key={sem.term + "_b"} info={bracketInfos[i]} />
                ))}
              </View>

              {/* Nodes row */}
              <View style={{ flexDirection: "row", alignItems: "flex-start" }}>
                {data.semesters.map((sem, i) => (
                  <TimelineNode
                    key={sem.term}
                    semester={sem}
                    selected={sem.term === selectedTerm}
                    onPress={() => setSelectedTerm(sem.term)}
                    isLast={i === data.semesters.length - 1}
                  />
                ))}
              </View>
            </View>
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
