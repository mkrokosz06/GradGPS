import React, { useEffect, useState, useCallback, useMemo } from "react";
import {
  View,
  Text,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  getCourseDetail,
  getProfessors,
  getProfessorByName,
  type CourseDetail,
  type ProfessorRating,
} from "../../services/courseService";

// ── Rating bar ────────────────────────────────────────────────────────────────

function RatingBar({ value, max = 5 }: { value: number; max?: number }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <View style={{ height: 6, backgroundColor: "#e5e7eb", borderRadius: 3, overflow: "hidden", flex: 1 }}>
      <View style={{ height: "100%", width: `${pct}%`, backgroundColor: "#1a3a6b", borderRadius: 3 }} />
    </View>
  );
}

function Stars({ rating }: { rating: number }) {
  const filled = Math.round(rating);
  return (
    <Text style={{ color: "#E8C84B", fontSize: 14, letterSpacing: 1 }}>
      {"★".repeat(filled)}{"☆".repeat(5 - filled)}
    </Text>
  );
}

// ── Professor card ────────────────────────────────────────────────────────────

function ProfessorCard({ prof, courseCode }: { prof: ProfessorRating; courseCode: string }) {
  const hasCourseRatings = prof.course_num_ratings >= 3;
  const lowCourseData    = prof.course_num_ratings > 0 && prof.course_num_ratings < 3;
  const noCourseData     = prof.course_num_ratings === 0;

  const displayRating     = (hasCourseRatings || lowCourseData) ? prof.course_avg_rating     : prof.overall_avg_rating;
  const displayDifficulty = (hasCourseRatings || lowCourseData) ? prof.course_avg_difficulty  : prof.overall_avg_difficulty;
  const displayWta        = (hasCourseRatings || lowCourseData) ? prof.course_would_take_again : prof.overall_would_take_again;

  return (
    <View style={{
      backgroundColor: "#fff",
      borderRadius: 14,
      borderWidth: 1,
      borderColor: "#e5e7eb",
      padding: 16,
      marginBottom: 12,
      shadowColor: "#000",
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.05,
      shadowRadius: 3,
      elevation: 2,
    }}>
      <Text style={{ fontSize: 16, fontWeight: "700", color: "#1a3a6b" }}>{prof.name}</Text>
      {prof.department ? (
        <Text style={{ fontSize: 12, color: "#9ca3af", marginTop: 2 }}>{prof.department}</Text>
      ) : null}

      {/* Data source badge */}
      <View style={{ marginTop: 10, marginBottom: 8 }}>
        {hasCourseRatings && (
          <View style={{ backgroundColor: "#dbeafe", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, alignSelf: "flex-start" }}>
            <Text style={{ fontSize: 11, fontWeight: "700", color: "#1a3a6b" }}>
              {prof.course_num_ratings} ratings for {courseCode}
            </Text>
          </View>
        )}
        {lowCourseData && (
          <View style={{ backgroundColor: "#fef9c3", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, alignSelf: "flex-start" }}>
            <Text style={{ fontSize: 11, fontWeight: "600", color: "#92400e" }}>
              Only {prof.course_num_ratings} rating{prof.course_num_ratings === 1 ? "" : "s"} for {courseCode}
            </Text>
          </View>
        )}
        {noCourseData && (
          <View style={{ backgroundColor: "#f3f4f6", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, alignSelf: "flex-start" }}>
            <Text style={{ fontSize: 11, fontWeight: "600", color: "#6b7280" }}>
              No ratings for {courseCode} — showing overall
            </Text>
          </View>
        )}
      </View>

      {displayRating != null ? (
        <>
          <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 6 }}>
            <Text style={{ fontSize: 36, fontWeight: "800", color: "#1a3a6b", marginRight: 10 }}>
              {displayRating.toFixed(1)}
            </Text>
            <View>
              <Stars rating={displayRating} />
              <Text style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>Quality</Text>
            </View>
          </View>

          {displayDifficulty != null && (
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 8 }}>
              <Text style={{ fontSize: 13, color: "#6b7280", width: 90 }}>Difficulty</Text>
              <RatingBar value={displayDifficulty} />
              <Text style={{ fontSize: 13, fontWeight: "600", color: "#374151", marginLeft: 8, width: 28 }}>
                {displayDifficulty.toFixed(1)}
              </Text>
            </View>
          )}

          {displayWta != null && displayWta >= 0 && (
            <Text style={{ fontSize: 13, color: "#6b7280" }}>
              <Text style={{
                fontWeight: "700",
                color: displayWta >= 70 ? "#15803d" : displayWta >= 40 ? "#b45309" : "#dc2626",
              }}>
                {Math.round(displayWta)}%
              </Text>
              {" would take again"}
            </Text>
          )}
        </>
      ) : (
        <Text style={{ color: "#9ca3af", fontSize: 13, marginTop: 4 }}>No rating data available</Text>
      )}

      {hasCourseRatings && prof.overall_avg_rating != null && (
        <Text style={{ fontSize: 11, color: "#9ca3af", marginTop: 10, borderTopWidth: 1, borderTopColor: "#f3f4f6", paddingTop: 8 }}>
          Overall: {prof.overall_avg_rating.toFixed(1)} ★ across {prof.overall_num_ratings} ratings
        </Text>
      )}
    </View>
  );
}

// ── Sort pills ────────────────────────────────────────────────────────────────

type SortKey = "best_rating" | "most_ratings" | "easiest" | "hardest" | "would_take_again";

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "most_ratings",     label: "Most Ratings" },
  { key: "best_rating",      label: "Best Rating" },
  { key: "easiest",          label: "Easiest" },
  { key: "hardest",          label: "Hardest" },
  { key: "would_take_again", label: "Would Take Again" },
];

function SortPills({ active, onSelect }: { active: SortKey; onSelect: (k: SortKey) => void }) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={{ marginBottom: 16 }}
      contentContainerStyle={{ gap: 8, paddingRight: 4 }}
    >
      {SORT_OPTIONS.map((opt) => {
        const isActive = active === opt.key;
        return (
          <TouchableOpacity
            key={opt.key}
            onPress={() => onSelect(opt.key)}
            style={{
              paddingHorizontal: 14, paddingVertical: 7,
              borderRadius: 20,
              backgroundColor: isActive ? "#1a3a6b" : "#f3f4f6",
              borderWidth: 1,
              borderColor: isActive ? "#1a3a6b" : "#e5e7eb",
            }}
          >
            <Text style={{ fontSize: 12, fontWeight: "700", color: isActive ? "#fff" : "#6b7280" }}>
              {opt.label}
            </Text>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
}

function sortProfessors(profs: ProfessorRating[], key: SortKey): ProfessorRating[] {
  const display = (p: ProfessorRating) => {
    const hasCourse = p.course_num_ratings > 0;
    return {
      rating:     hasCourse ? p.course_avg_rating     : p.overall_avg_rating,
      difficulty: hasCourse ? p.course_avg_difficulty  : p.overall_avg_difficulty,
      wta:        hasCourse ? p.course_would_take_again : p.overall_would_take_again,
    };
  };

  return [...profs].sort((a, b) => {
    const da = display(a);
    const db = display(b);

    const nullLast = (va: number | null, vb: number | null, asc: boolean): number => {
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return asc ? va - vb : vb - va;
    };

    switch (key) {
      case "best_rating":      return nullLast(da.rating,     db.rating,     false);
      case "most_ratings":     return (b.course_num_ratings  - a.course_num_ratings) || nullLast(da.rating, db.rating, false);
      case "easiest":          return nullLast(da.difficulty, db.difficulty, true);
      case "hardest":          return nullLast(da.difficulty, db.difficulty, false);
      case "would_take_again": return nullLast(da.wta,        db.wta,        false);
    }
  });
}

// ── Main screen ───────────────────────────────────────────────────────────────

export default function CourseDetailScreen() {
  const router = useRouter();
  const { code } = useLocalSearchParams<{ code: string }>();

  const [detail, setDetail]               = useState<CourseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);

  const [professors, setProfessors]         = useState<ProfessorRating[]>([]);
  const [autoLoading, setAutoLoading]       = useState(true);
  const [autoError, setAutoError]           = useState(false);
  const [sortKey, setSortKey]               = useState<SortKey>("most_ratings");
  const [searchName, setSearchName]         = useState("");
  const [searching, setSearching]           = useState(false);
  const [searchError, setSearchError]       = useState<string | null>(null);
  const [hasSearched, setHasSearched]       = useState(false);

  const sortedProfessors = useMemo(
    () => sortProfessors(professors, sortKey),
    [professors, sortKey],
  );

  useEffect(() => {
    if (!code) return;
    getCourseDetail(code)
      .then(setDetail)
      .catch(() => {})
      .finally(() => setDetailLoading(false));

    // Auto-load professors from index
    getProfessors(code)
      .then(({ professors: profs }) => {
        setProfessors(profs);
        setAutoLoading(false);
      })
      .catch(() => {
        setAutoError(true);
        setAutoLoading(false);
      });
  }, [code]);

  const runSearch = useCallback(async () => {
    const q = searchName.trim();
    if (!q || !code) return;
    setSearching(true);
    setSearchError(null);
    setHasSearched(true);
    try {
      const results = await getProfessorByName(code, q);
      setProfessors(results);
      if (results.length === 0) setSearchError(`No Penn State professors found for "${q}"`);
    } catch {
      setSearchError("Search failed — check your connection and try again");
    } finally {
      setSearching(false);
    }
  }, [searchName, code]);

  const displayCode = code ?? "";

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#fff" }} edges={["top", "left", "right"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>

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
            {displayCode}
          </Text>
        </View>

        <ScrollView
          contentContainerStyle={{ padding: 20, paddingBottom: 48 }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* ── Course info ── */}
          {detailLoading ? (
            <ActivityIndicator color="#1a3a6b" style={{ marginVertical: 16 }} />
          ) : detail ? (
            <View style={{ marginBottom: 28 }}>
              {detail.course_title ? (
                <Text style={{ fontSize: 20, fontWeight: "800", color: "#1a3a6b", marginBottom: 10 }}>
                  {detail.course_title}
                </Text>
              ) : null}
              {detail.credits > 0 && (
                <View style={{ flexDirection: "row" }}>
                  <View style={{ backgroundColor: "#dbeafe", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 }}>
                    <Text style={{ fontSize: 12, fontWeight: "700", color: "#1a3a6b" }}>
                      {detail.credits} credits
                    </Text>
                  </View>
                </View>
              )}
            </View>
          ) : null}

          {/* ── Rate My Professor ── */}
          <View style={{ borderTopWidth: detail ? 1 : 0, borderTopColor: "#f3f4f6", paddingTop: detail ? 24 : 0 }}>
            <Text style={{ fontSize: 16, fontWeight: "800", color: "#1a3a6b", marginBottom: 4 }}>
              Rate My Professor
            </Text>

            {/* Auto-loaded professors */}
            {autoLoading ? (
              <View style={{ paddingVertical: 24, alignItems: "center" }}>
                <ActivityIndicator color="#1a3a6b" />
                <Text style={{ fontSize: 13, color: "#9ca3af", marginTop: 8 }}>
                  Loading professors for {displayCode}…
                </Text>
              </View>
            ) : professors.length > 0 && !hasSearched ? (
              <>
                <Text style={{ fontSize: 13, color: "#9ca3af", marginBottom: 14 }}>
                  Professor ratings for {displayCode}
                </Text>

                {/* Sort pills */}
                <SortPills active={sortKey} onSelect={setSortKey} />

                {sortedProfessors.map((prof) => (
                  <ProfessorCard key={prof.id} prof={prof} courseCode={displayCode} />
                ))}
              </>
            ) : null}

            {/* Manual search — always visible, replaces auto results when used */}
            <View style={{ marginTop: professors.length > 0 && !hasSearched ? 16 : 0 }}>
              <Text style={{ fontSize: 13, color: "#9ca3af", marginBottom: 10 }}>
                {professors.length > 0 && !hasSearched
                  ? "Don't see your professor? Search by name:"
                  : autoError
                    ? "Couldn't load professors. Search by name:"
                    : !autoLoading && professors.length === 0
                      ? `No professors found for ${displayCode}. Search by name:`
                      : ""}
              </Text>
              <View style={{ flexDirection: "row", gap: 8, marginBottom: 20 }}>
                <TextInput
                  value={searchName}
                  onChangeText={setSearchName}
                  onSubmitEditing={runSearch}
                  returnKeyType="search"
                  placeholder="Professor last name or full name"
                  placeholderTextColor="#9ca3af"
                  style={{
                    flex: 1, height: 46,
                    backgroundColor: "#f9fafb",
                    borderWidth: 1, borderColor: "#e5e7eb",
                    borderRadius: 10, paddingHorizontal: 14,
                    fontSize: 14, color: "#1f2937",
                  }}
                />
                <TouchableOpacity
                  onPress={runSearch}
                  disabled={searching || !searchName.trim()}
                  style={{
                    height: 46, paddingHorizontal: 18,
                    backgroundColor: searchName.trim() ? "#1a3a6b" : "#e5e7eb",
                    borderRadius: 10,
                    alignItems: "center", justifyContent: "center",
                  }}
                >
                  {searching
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Text style={{ color: searchName.trim() ? "#fff" : "#9ca3af", fontWeight: "700", fontSize: 14 }}>Search</Text>
                  }
                </TouchableOpacity>
              </View>

              {searchError ? (
                <Text style={{ color: "#6b7280", fontSize: 13, marginBottom: 12, textAlign: "center" }}>
                  {searchError}
                </Text>
              ) : null}

              {/* Search results — also use sortedProfessors so filter works on manual search too */}
              {hasSearched && (
                <>
                  {professors.length > 1 && (
                    <SortPills active={sortKey} onSelect={setSortKey} />
                  )}
                  {sortedProfessors.map((prof) => (
                    <ProfessorCard key={prof.id} prof={prof} courseCode={displayCode} />
                  ))}
                </>
              )}
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
