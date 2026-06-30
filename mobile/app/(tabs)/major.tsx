import React, { useState, useEffect, useMemo } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  FlatList,
  ActivityIndicator,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { NavHeader } from "../../components/NavHeader";
import { useAuth } from "../../context/AuthContext";
import { getAllPrograms, getSubplans, selectMajor } from "../../services/programService";

// ── Types ─────────────────────────────────────────────────────────────────────

type Screen = "search" | "subplan" | "saved";

// ── Main screen ───────────────────────────────────────────────────────────────

export default function MajorScreen() {
  const router = useRouter();
  const { userId } = useAuth();

  const [screen, setScreen]           = useState<Screen>("search");
  const [query, setQuery]             = useState("");
  const [allPrograms, setAllPrograms] = useState<string[]>([]);
  const [loading, setLoading]         = useState(true);

  // Subplan step
  const [pendingMajor, setPendingMajor]       = useState<string | null>(null);
  const [subplans, setSubplans]               = useState<string[]>([]);
  const [loadingSubplans, setLoadingSubplans] = useState(false);

  // Confirmed selection
  const [savedMajor, setSavedMajor]     = useState<string | null>(null);
  const [savedSubplan, setSavedSubplan] = useState<string | null>(null);
  const [saving, setSaving]             = useState(false);

  useEffect(() => {
    getAllPrograms()
      .then(setAllPrograms)
      .catch(() => Alert.alert("Error", "Could not load programs list."))
      .finally(() => setLoading(false));
  }, []);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allPrograms;
    return allPrograms.filter(n => n.toLowerCase().includes(q));
  }, [query, allPrograms]);

  // Step 1 — user taps a major from the list
  async function handleMajorPress(major: string) {
    setPendingMajor(major);
    setLoadingSubplans(true);
    try {
      let plans: string[] = [];
      try {
        plans = await getSubplans(major);
      } catch {
        // subplan check failed — proceed as if no subplans
        plans = [];
      }
      if (plans.length > 0) {
        setSubplans(plans);
        setScreen("subplan");
      } else {
        await saveMajor(major, null);
      }
    } finally {
      setLoadingSubplans(false);
    }
  }

  // Step 2 — user picks a subplan (or taps "No preference")
  async function handleSubplanPress(subplan: string | null) {
    if (!pendingMajor) return;
    await saveMajor(pendingMajor, subplan);
  }

  async function saveMajor(major: string, subplan: string | null) {
    setSaving(true);
    try {
      await selectMajor(userId!, major, subplan);
      setSavedMajor(major);
      setSavedSubplan(subplan);
      setQuery("");
      setScreen("saved");
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "Could not save major.");
    } finally {
      setSaving(false);
    }
  }

  // ── Subplan picker screen ──────────────────────────────────────────────────
  if (screen === "subplan" && pendingMajor) {
    return (
      <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
        <NavHeader subtitle="Choose a Track" />

        {/* Back + major name */}
        <View style={{ paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: "#f3f4f6" }}>
          <TouchableOpacity onPress={() => setScreen("search")} style={{ marginBottom: 10 }}>
            <Text style={{ color: "#1a3a6b", fontSize: 13, fontWeight: "600" }}>← Back to search</Text>
          </TouchableOpacity>
          <Text style={{ color: "#64748b", fontSize: 11, fontWeight: "700", letterSpacing: 0.5 }}>MAJOR</Text>
          <Text style={{ color: "#0f172a", fontSize: 14, fontWeight: "600", marginTop: 2 }}>{pendingMajor}</Text>
        </View>

        <Text style={{ paddingHorizontal: 20, paddingTop: 18, paddingBottom: 8, color: "#64748b", fontSize: 12, fontWeight: "600", letterSpacing: 0.5 }}>
          SELECT A TRACK / OPTION
        </Text>

        {saving && (
          <View style={{ alignItems: "center", paddingTop: 24 }}>
            <ActivityIndicator color="#1a3a6b" />
          </View>
        )}

        <FlatList
          data={subplans}
          keyExtractor={(item) => item}
          renderItem={({ item }) => (
            <TouchableOpacity
              onPress={() => handleSubplanPress(item)}
              disabled={saving}
              activeOpacity={0.6}
              style={{
                paddingHorizontal: 20, paddingVertical: 16,
                borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
                flexDirection: "row", alignItems: "center", justifyContent: "space-between",
              }}
            >
              <Text style={{ color: "#1e293b", fontSize: 13, flex: 1, marginRight: 12 }}>{item}</Text>
              <Text style={{ color: "#1a3a6b", fontSize: 13, fontWeight: "700" }}>Select</Text>
            </TouchableOpacity>
          )}
          ListFooterComponent={
            <TouchableOpacity
              onPress={() => handleSubplanPress(null)}
              disabled={saving}
              activeOpacity={0.6}
              style={{
                paddingHorizontal: 20, paddingVertical: 16,
                borderTopWidth: 1, borderTopColor: "#e2e8f0", marginTop: 8,
              }}
            >
              <Text style={{ color: "#94a3b8", fontSize: 13 }}>No preference / Undecided</Text>
            </TouchableOpacity>
          }
        />
      </SafeAreaView>
    );
  }

  // ── Saved confirmation screen ──────────────────────────────────────────────
  if (screen === "saved" && savedMajor) {
    return (
      <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
        <NavHeader subtitle="Change Major" />
        <View style={{ flex: 1, justifyContent: "center", alignItems: "center", paddingHorizontal: 32 }}>
          <View style={{
            width: 56, height: 56, borderRadius: 28,
            backgroundColor: "#f0fdf4", alignItems: "center", justifyContent: "center",
            marginBottom: 20,
          }}>
            <Text style={{ fontSize: 26 }}>✓</Text>
          </View>
          <Text style={{ color: "#166534", fontSize: 18, fontWeight: "700", marginBottom: 6, textAlign: "center" }}>
            Major Saved
          </Text>
          <Text style={{ color: "#1e293b", fontSize: 14, fontWeight: "500", textAlign: "center", marginBottom: 4 }}>
            {savedMajor}
          </Text>
          {savedSubplan && (
            <Text style={{ color: "#64748b", fontSize: 13, textAlign: "center", marginBottom: 20 }}>
              {savedSubplan}
            </Text>
          )}
          <TouchableOpacity
            onPress={() => router.navigate("/(tabs)/" as any)}
            style={{
              backgroundColor: "#1a3a6b",
              paddingHorizontal: 28, paddingVertical: 14, borderRadius: 14,
              marginBottom: 12,
            }}
          >
            <Text style={{ color: "#ffffff", fontWeight: "700", fontSize: 14 }}>Return to Timeline</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setScreen("search")}>
            <Text style={{ color: "#94a3b8", fontSize: 13, marginTop: 4 }}>Change Major</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // ── Major search screen (default) ─────────────────────────────────────────
  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top", "left", "right"]}>
      <NavHeader subtitle="Change Major" />

      {/* Search bar */}
      <View className="px-5 pt-5 pb-3 border-b border-gray-100">
        <View
          style={{
            flexDirection: "row", alignItems: "center",
            backgroundColor: "#f8fafc", borderRadius: 14,
            borderWidth: 1.5, borderColor: "#e2e8f0", paddingHorizontal: 14,
          }}
        >
          <Text style={{ color: "#94a3b8", fontSize: 15, marginRight: 8 }}>⌕</Text>
          <TextInput
            style={{ flex: 1, color: "#111827", paddingVertical: 13, fontSize: 14 }}
            placeholder="Search Penn State majors…"
            placeholderTextColor="#94a3b8"
            value={query}
            onChangeText={setQuery}
            autoCapitalize="none"
            returnKeyType="search"
          />
          {loading || loadingSubplans
            ? <ActivityIndicator size="small" color="#1a3a6b" />
            : query.length > 0
            ? (
              <TouchableOpacity onPress={() => setQuery("")}>
                <Text style={{ color: "#94a3b8", fontSize: 16, paddingLeft: 8 }}>×</Text>
              </TouchableOpacity>
            ) : null}
        </View>
      </View>

      {/* Results list */}
      <FlatList
        data={results}
        keyExtractor={(item) => item}
        contentContainerStyle={{ paddingTop: 8 }}
        renderItem={({ item }) => (
          <TouchableOpacity
            onPress={() => handleMajorPress(item)}
            disabled={loadingSubplans || saving}
            activeOpacity={0.6}
            style={{
              paddingHorizontal: 20, paddingVertical: 15,
              borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
              flexDirection: "row", alignItems: "center", justifyContent: "space-between",
            }}
          >
            <Text style={{ color: "#1e293b", fontSize: 13, flex: 1, marginRight: 12 }}>{item}</Text>
            <Text style={{ color: "#1a3a6b", fontSize: 13, fontWeight: "700" }}>Select</Text>
          </TouchableOpacity>
        )}
        ListEmptyComponent={
          loading ? null : (
            <View style={{ alignItems: "center", paddingTop: 48 }}>
              <Text style={{ color: "#cbd5e1", fontSize: 14 }}>No programs found</Text>
            </View>
          )
        }
        keyboardShouldPersistTaps="handled"
      />
    </SafeAreaView>
  );
}
