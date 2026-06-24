import React, { useState, useEffect, useMemo } from "react";
import {
  View, Text, TextInput, TouchableOpacity,
  FlatList, ActivityIndicator, StyleSheet, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useAuth } from "../../context/AuthContext";
import { getAllPrograms, getSubplans, selectMajor } from "../../services/programService";

function StepDots({ step }: { step: number }) {
  return (
    <View style={{ flexDirection: "row", gap: 6, justifyContent: "center", marginBottom: 32 }}>
      {[0, 1, 2].map((i) => (
        <View key={i} style={{
          height: 5, borderRadius: 3,
          width: i === step ? 22 : 6,
          backgroundColor: i <= step ? "#1a3a6b" : "#e2e8f0",
        }} />
      ))}
    </View>
  );
}

export default function OnboardingMajorScreen() {
  const router     = useRouter();
  const { userId } = useAuth();

  const [allPrograms, setAllPrograms] = useState<string[]>([]);
  const [query,       setQuery]       = useState("");
  const [loading,     setLoading]     = useState(true);
  const [saving,      setSaving]      = useState(false);
  const [subplans,    setSubplans]    = useState<string[] | null>(null);
  const [pending,     setPending]     = useState<string | null>(null);

  useEffect(() => {
    getAllPrograms()
      .then(setAllPrograms)
      .catch(() => Alert.alert("Error", "Could not load programs."))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allPrograms;
    return allPrograms.filter((n) => n.toLowerCase().includes(q));
  }, [query, allPrograms]);

  async function handleMajorSelect(major: string) {
    setSaving(true);
    try {
      const plans = await getSubplans(major);
      if (plans.length > 0) {
        setPending(major);
        setSubplans(plans);
      } else {
        await saveMajor(major, null);
      }
    } catch {
      Alert.alert("Error", "Could not check tracks.");
    } finally {
      setSaving(false);
    }
  }

  async function saveMajor(major: string, subplan: string | null) {
    setSaving(true);
    try {
      await selectMajor(userId!, major, subplan);
      router.push("/onboarding/upload" as any);
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "Could not save major.");
    } finally {
      setSaving(false);
    }
  }

  // ── Subplan picker ────────────────────────────────────────────────────────
  if (subplans && pending) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.container}>
          <StepDots step={1} />
          <TouchableOpacity onPress={() => { setSubplans(null); setPending(null); }} style={{ marginBottom: 20 }}>
            <Text style={{ color: "#1a3a6b", fontWeight: "600", fontSize: 13 }}>← Back</Text>
          </TouchableOpacity>
          <Text style={styles.heading}>Choose a track</Text>
          <Text style={[styles.sub, { marginBottom: 24 }]} numberOfLines={2}>{pending}</Text>

          {saving && <ActivityIndicator color="#1a3a6b" style={{ marginBottom: 12 }} />}

          <FlatList
            data={subplans}
            keyExtractor={(item) => item}
            renderItem={({ item }) => (
              <TouchableOpacity
                onPress={() => saveMajor(pending, item)}
                disabled={saving}
                activeOpacity={0.6}
                style={styles.listRow}
              >
                <Text style={styles.listRowText}>{item}</Text>
                <Text style={styles.selectLabel}>Select</Text>
              </TouchableOpacity>
            )}
            ListFooterComponent={
              <TouchableOpacity onPress={() => saveMajor(pending, null)} disabled={saving} style={styles.skipRow}>
                <Text style={{ color: "#94a3b8", fontSize: 13 }}>Undecided / No preference</Text>
              </TouchableOpacity>
            }
          />
        </View>
      </SafeAreaView>
    );
  }

  // ── Major search ──────────────────────────────────────────────────────────
  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <StepDots step={1} />
        <Text style={styles.heading}>What's your major?</Text>
        <Text style={styles.sub}>Search for your Penn State program.</Text>

        <View style={styles.searchBox}>
          <Text style={{ color: "#94a3b8", fontSize: 15, marginRight: 8 }}>⌕</Text>
          <TextInput
            style={styles.searchInput}
            placeholder="e.g. Information Sciences..."
            placeholderTextColor="#94a3b8"
            value={query}
            onChangeText={setQuery}
            autoCapitalize="none"
          />
          {loading
            ? <ActivityIndicator size="small" color="#1a3a6b" />
            : query.length > 0
            ? <TouchableOpacity onPress={() => setQuery("")}>
                <Text style={{ color: "#94a3b8", fontSize: 18 }}>×</Text>
              </TouchableOpacity>
            : null}
        </View>

        {saving && (
          <View style={{ alignItems: "center", paddingTop: 12 }}>
            <ActivityIndicator color="#1a3a6b" />
          </View>
        )}

        <FlatList
          data={filtered}
          keyExtractor={(item) => item}
          keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => (
            <TouchableOpacity
              onPress={() => handleMajorSelect(item)}
              disabled={saving}
              activeOpacity={0.6}
              style={styles.listRow}
            >
              <Text style={[styles.listRowText, { flex: 1, marginRight: 12 }]}>{item}</Text>
              <Text style={styles.selectLabel}>Select</Text>
            </TouchableOpacity>
          )}
          ListEmptyComponent={
            !loading && query.length >= 2 ? (
              <Text style={{ color: "#cbd5e1", textAlign: "center", marginTop: 32, fontSize: 14 }}>
                No programs found
              </Text>
            ) : null
          }
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:        { flex: 1, backgroundColor: "#ffffff" },
  container:   { flex: 1, paddingHorizontal: 24, paddingTop: 48 },
  heading:     { fontSize: 28, fontWeight: "800", color: "#0f172a", marginBottom: 6 },
  sub:         { fontSize: 14, color: "#94a3b8", marginBottom: 24 },
  searchBox:   {
    flexDirection: "row", alignItems: "center",
    backgroundColor: "#f8fafc", borderRadius: 14,
    borderWidth: 1.5, borderColor: "#e2e8f0",
    paddingHorizontal: 14, marginBottom: 8,
  },
  searchInput: { flex: 1, fontSize: 14, color: "#0f172a", paddingVertical: 13 },
  listRow:     {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 15, paddingHorizontal: 4,
    borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
  },
  listRowText: { color: "#1e293b", fontSize: 13 },
  selectLabel: { color: "#1a3a6b", fontSize: 13, fontWeight: "700" },
  skipRow:     { paddingVertical: 16, paddingHorizontal: 4, marginTop: 8 },
});
