import React, { useCallback, useState } from "react";
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
import { getAudit, type AuditSummary } from "../../services/auditService";
import { getTimeline, type TimelineData, type TimelineCourse, type Semester } from "../../services/timelineService";

// ── Helpers ───────────────────────────────────────────────────────────────────

function greeting(name: string | null): string {
  const hour = new Date().getHours();
  const sal  = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const first = name?.trim().split(" ")[0] ?? null;
  return first ? `${sal}, ${first}` : sal;
}

function courseType(c: TimelineCourse): { label: string; bg: string; color: string } {
  if (c.is_pool || (c.gen_ed_categories && c.gen_ed_categories.length > 0)) {
    return { label: "Gen Ed / Elective", bg: "#f0fdf4", color: "#15803d" };
  }
  return { label: "Required", bg: "#f0f4ff", color: "#1a3a6b" };
}

// ── State 1: Welcome ──────────────────────────────────────────────────────────

function WelcomeState() {
  const router = useRouter();
  return (
    <View style={{ flex: 1, backgroundColor: "#1a3a6b", paddingHorizontal: 32, justifyContent: "center" }}>
      <Text style={{
        color: "#E8C84B", fontSize: 12, fontWeight: "800",
        letterSpacing: 2.5, marginBottom: 20,
      }}>
        GRADGPS
      </Text>
      <Text style={{
        color: "#ffffff", fontSize: 38, fontWeight: "900",
        lineHeight: 44, marginBottom: 16,
      }}>
        Your Penn State degree, mapped.
      </Text>
      <Text style={{
        color: "rgba(255,255,255,0.55)", fontSize: 15,
        lineHeight: 23, marginBottom: 52,
      }}>
        Build your 4-year plan, track your progress, and find the best professors — all in one place.
      </Text>
      <TouchableOpacity
        activeOpacity={0.85}
        onPress={() => router.navigate("/major" as any)}
        style={{
          backgroundColor: "#E8C84B", borderRadius: 14,
          paddingVertical: 17, alignItems: "center",
        }}
      >
        <Text style={{ color: "#1a3a6b", fontSize: 16, fontWeight: "800" }}>Get started →</Text>
      </TouchableOpacity>
    </View>
  );
}

// ── No-transcript banner (shown instead of CurrentSemesterStrip) ──────────────

function NoTranscriptBanner() {
  const router = useRouter();
  return (
    <TouchableOpacity
      activeOpacity={0.85}
      onPress={() => router.navigate("/upload" as any)}
      style={{
        backgroundColor: "#fffbeb", borderRadius: 16,
        paddingHorizontal: 18, paddingVertical: 14,
        marginBottom: 14, borderWidth: 1, borderColor: "#fde68a",
        flexDirection: "row", alignItems: "center", gap: 12,
      }}
    >
      <View style={{ flex: 1 }}>
        <Text style={{ color: "#92400e", fontSize: 13, fontWeight: "700", marginBottom: 2 }}>
          Projected plan — no transcript
        </Text>
        <Text style={{ color: "#a16207", fontSize: 12, lineHeight: 17 }}>
          Upload your transcript to track completed courses and personalize this timeline.
        </Text>
      </View>
      <Text style={{ color: "#92400e", fontSize: 16 }}>→</Text>
    </TouchableOpacity>
  );
}

// ── State 3: Registration view ────────────────────────────────────────────────

function CurrentSemesterStrip({ semester, credits }: { semester: Semester; credits: number }) {
  const router   = useRouter();
  const courses  = semester.courses.filter((c) => !c.is_pool);
  const shown    = courses.slice(0, 3);
  const extra    = courses.length - shown.length;

  return (
    <TouchableOpacity
      activeOpacity={0.85}
      onPress={() => router.navigate("/timeline" as any)}
      style={{
        backgroundColor: "#ffffff", borderRadius: 16,
        paddingHorizontal: 18, paddingVertical: 14,
        marginBottom: 14, borderWidth: 1, borderColor: "#f1f5f9",
        shadowColor: "#1a3a6b", shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.06, shadowRadius: 6, elevation: 2,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 8, gap: 8 }}>
            <Text style={{ color: "#1a3a6b", fontSize: 15, fontWeight: "800" }}>
              {semester.label}
            </Text>
            <View style={{
              backgroundColor: "#fef3c7", borderRadius: 6,
              paddingHorizontal: 8, paddingVertical: 2,
            }}>
              <Text style={{ color: "#92400e", fontSize: 10, fontWeight: "700" }}>In Progress</Text>
            </View>
          </View>
          <Text style={{ color: "#94a3b8", fontSize: 12 }}>
            {shown.map((c) => c.course_code).join(" · ")}
            {extra > 0 ? ` · +${extra} more` : ""}
          </Text>
        </View>
        <View style={{ alignItems: "flex-end", marginLeft: 12 }}>
          <Text style={{ color: "#1a3a6b", fontSize: 18, fontWeight: "800" }}>{credits}</Text>
          <Text style={{ color: "#94a3b8", fontSize: 10 }}>credits</Text>
        </View>
      </View>
    </TouchableOpacity>
  );
}

function RegistrationCourseRow({ course }: { course: TimelineCourse }) {
  const router = useRouter();
  const type   = courseType(course);

  if (course.is_pool) {
    // Single gen ed category slot (one per missing category)
    const cats = course.gen_ed_categories;
    const isGenEdSlot = cats && cats.length === 1
      && course.pool_needed_credits == null
      && course.pool_needed_courses == null;

    let poolLabel: string;
    if (isGenEdSlot) {
      poolLabel = `Gen Ed — ${cats![0]}`;
    } else {
      const needed = course.pool_needed_credits ?? course.pool_needed_courses ?? 0;
      const unit   = course.pool_needed_credits != null ? "credits" : "courses";
      poolLabel = `Elective Pool — ${needed} ${unit}`;
    }

    return (
      <View style={{
        flexDirection: "row", alignItems: "center",
        paddingVertical: 14, paddingHorizontal: 18,
        borderBottomWidth: 1, borderBottomColor: "#f8fafc",
        opacity: 0.55,
      }}>
        <View style={{
          width: 9, height: 9, borderRadius: 4.5,
          borderWidth: 2, borderColor: "#cbd5e1", marginRight: 14,
        }} />
        <View style={{ flex: 1 }}>
          <Text style={{ color: "#64748b", fontSize: 13, fontWeight: "600" }}>
            {poolLabel}
          </Text>
        </View>
        <View style={{
          backgroundColor: type.bg, borderRadius: 7,
          paddingHorizontal: 9, paddingVertical: 4,
        }}>
          <Text style={{ color: type.color, fontSize: 10, fontWeight: "700" }}>{type.label}</Text>
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
      activeOpacity={0.75}
      onPress={handlePress}
      style={{
        flexDirection: "row", alignItems: "center",
        paddingVertical: 14, paddingHorizontal: 18,
        borderBottomWidth: 1, borderBottomColor: "#f8fafc",
      }}
    >
      {/* Unchecked circle — visual checklist feel */}
      <View style={{
        width: 20, height: 20, borderRadius: 10,
        borderWidth: 2, borderColor: "#d1d9e6",
        marginRight: 14, flexShrink: 0,
      }} />

      <View style={{ flex: 1 }}>
        <Text style={{ color: "#1a3a6b", fontSize: 14, fontWeight: "700" }}>
          {course.course_code}
        </Text>
        {course.course_title ? (
          <Text style={{ color: "#64748b", fontSize: 12, marginTop: 2 }} numberOfLines={1}>
            {course.course_title}
          </Text>
        ) : null}
      </View>

      <View style={{ alignItems: "flex-end", gap: 6, marginLeft: 10 }}>
        <View style={{
          backgroundColor: type.bg, borderRadius: 7,
          paddingHorizontal: 9, paddingVertical: 4,
        }}>
          <Text style={{ color: type.color, fontSize: 10, fontWeight: "700" }}>{type.label}</Text>
        </View>
        <Text style={{ color: "#94a3b8", fontSize: 11 }}>Tap for ratings</Text>
      </View>
    </TouchableOpacity>
  );
}

function RegistrationSection({ semester, audit }: { semester: Semester; audit: AuditSummary }) {
  const router  = useRouter();
  const courses = semester.courses;

  return (
    <View style={{
      backgroundColor: "#ffffff", borderRadius: 20,
      borderWidth: 1, borderColor: "#f1f5f9",
      shadowColor: "#1a3a6b", shadowOffset: { width: 0, height: 3 },
      shadowOpacity: 0.07, shadowRadius: 10, elevation: 3,
      overflow: "hidden",
    }}>
      {/* Section header */}
      <View style={{ paddingHorizontal: 18, paddingTop: 20, paddingBottom: 16 }}>
        <Text style={{
          color: "#94a3b8", fontSize: 11, fontWeight: "700",
          letterSpacing: 0.9, marginBottom: 6,
        }}>
          PLAN YOUR REGISTRATION
        </Text>
        <Text style={{ color: "#1a3a6b", fontSize: 21, fontWeight: "900" }}>
          {semester.label}
        </Text>
        <Text style={{ color: "#64748b", fontSize: 13, marginTop: 4 }}>
          {courses.filter((c) => !c.is_pool).length} courses recommended · ~{semester.credits} credits
        </Text>
      </View>

      {/* Divider */}
      <View style={{ height: 1, backgroundColor: "#f1f5f9", marginBottom: 4 }} />

      {/* Course list */}
      {courses.map((c, i) => (
        <RegistrationCourseRow key={`${c.course_code}_${i}`} course={c} />
      ))}

      {/* Footer */}
      <TouchableOpacity
        activeOpacity={0.75}
        onPress={() => router.navigate("/timeline" as any)}
        style={{
          flexDirection: "row", justifyContent: "center", alignItems: "center",
          paddingVertical: 16, borderTopWidth: 1, borderTopColor: "#f8fafc",
          gap: 6,
        }}
      >
        <Text style={{ color: "#2a5298", fontSize: 13, fontWeight: "700" }}>
          View full degree plan
        </Text>
        <Text style={{ color: "#2a5298", fontSize: 13 }}>→</Text>
      </TouchableOpacity>
    </View>
  );
}

function AllDoneCard({ gradLabel }: { gradLabel: string | null }) {
  return (
    <View style={{
      backgroundColor: "#1a3a6b", borderRadius: 20, padding: 28,
      alignItems: "center",
    }}>
      <Text style={{ color: "#E8C84B", fontSize: 32, marginBottom: 12 }}>🎓</Text>
      <Text style={{ color: "#ffffff", fontSize: 20, fontWeight: "800", marginBottom: 8, textAlign: "center" }}>
        You're all set
      </Text>
      <Text style={{ color: "rgba(255,255,255,0.6)", fontSize: 14, textAlign: "center", lineHeight: 20 }}>
        No more semesters to plan.
        {gradLabel ? ` Estimated graduation: ${gradLabel}.` : ""}
      </Text>
    </View>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export default function HomeScreen() {
  const { userId, name } = useAuth();
  const router = useRouter();

  const [audit,      setAudit]      = useState<AuditSummary | null>(null);
  const [timeline,   setTimeline]   = useState<TimelineData | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async () => {
    if (!userId) { setLoading(false); return; }
    try {
      const [a, t] = await Promise.all([
        getAudit(userId).catch(() => null),
        getTimeline(userId).catch(() => null),
      ]);
      setAudit(a);
      setTimeline(t);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [userId]);

  useFocusEffect(useCallback(() => { fetchData(); }, [fetchData]));
  const onRefresh = useCallback(() => { setRefreshing(true); fetchData(); }, [fetchData]);

  if (loading) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: "#f8fafc" }} edges={["top", "left", "right"]}>
        <NavHeader />
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator size="large" color="#1a3a6b" />
        </View>
      </SafeAreaView>
    );
  }

  // ── State detection ───────────────────────────────────────────────────────
  const hasMajor      = !!(audit?.major);
  const hasTranscript = !!(audit?.transcript_credits && audit.transcript_credits > 0);

  // State 1 — no major
  if (!hasMajor) {
    return (
      <SafeAreaView style={{ flex: 1 }} edges={["top", "left", "right"]}>
        <WelcomeState />
      </SafeAreaView>
    );
  }

  // State 2 & 3 — major picked (with or without transcript)
  const currentSem = timeline?.semesters.find((s) => s.status === "current") ?? null;
  const nextSem    = timeline?.semesters.find((s) => s.status === "upcoming") ?? null;
  const upcoming   = timeline?.semesters.filter((s) => s.status === "upcoming") ?? [];
  const gradLabel  = upcoming.length > 0 ? upcoming[upcoming.length - 1].label : null;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#f8fafc" }} edges={["top", "left", "right"]}>
      <NavHeader />
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 8, paddingBottom: 48 }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#1a3a6b" />
        }
      >
        <Text style={{
          color: "#1a3a6b", fontSize: 24, fontWeight: "900",
          marginBottom: 16, marginTop: 10, letterSpacing: -0.5,
        }}>
          {greeting(name)}
        </Text>

        {hasTranscript && currentSem ? (
          <CurrentSemesterStrip semester={currentSem} credits={audit!.transcript_credits} />
        ) : !hasTranscript ? (
          <NoTranscriptBanner />
        ) : null}

        {nextSem ? (
          <RegistrationSection semester={nextSem} audit={audit!} />
        ) : (
          <AllDoneCard gradLabel={gradLabel} />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
