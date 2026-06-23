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
import axios from "axios";
import { API_BASE, USER_ID } from "../../constants/api";
import { NavHeader } from "../../components/NavHeader";

export default function MajorScreen() {
  const [query, setQuery]         = useState("");
  const [allPrograms, setAllPrograms] = useState<string[]>([]);
  const [loading, setLoading]     = useState(true);
  const [saving, setSaving]       = useState(false);
  const [selected, setSelected]   = useState<string | null>(null);

  useEffect(() => {
    axios.get<{ results: string[] }>(`${API_BASE}/programs/all`)
      .then(res => setAllPrograms(res.data.results))
      .catch(() => Alert.alert("Error", "Could not load programs list."))
      .finally(() => setLoading(false));
  }, []);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allPrograms;
    return allPrograms.filter(n => n.toLowerCase().includes(q));
  }, [query, allPrograms]);

  async function selectMajor(major: string) {
    setSaving(true);
    try {
      await axios.post(
        `${API_BASE}/programs/select`,
        { major },
        { headers: { "x-user-id": USER_ID } },
      );
      setSelected(major);
      setQuery("");
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "Could not save major.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-white" edges={["top","left","right"]}>
      <NavHeader subtitle="Change Major" />

      {/* Search bar */}
      <View className="px-5 pt-5 pb-3 border-b border-gray-100">
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: "#f8fafc",
            borderRadius: 14,
            borderWidth: 1.5,
            borderColor: "#e2e8f0",
            paddingHorizontal: 14,
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
          {loading
            ? <ActivityIndicator size="small" color="#1a3a6b" />
            : query.length > 0
            ? (
              <TouchableOpacity onPress={() => setQuery("")}>
                <Text style={{ color: "#94a3b8", fontSize: 16, paddingLeft: 8 }}>×</Text>
              </TouchableOpacity>
            ) : null}
        </View>
      </View>

      {/* Current major banner */}
      {selected && (
        <View
          style={{
            marginHorizontal: 20, marginTop: 14,
            backgroundColor: "#f0fdf4",
            borderRadius: 14, borderWidth: 1, borderColor: "#bbf7d0",
            padding: 14,
          }}
        >
          <Text style={{ color: "#16a34a", fontSize: 11, fontWeight: "700", marginBottom: 3 }}>
            MAJOR SAVED
          </Text>
          <Text style={{ color: "#166534", fontSize: 13, fontWeight: "500" }}>{selected}</Text>
          <Text style={{ color: "#4ade80", fontSize: 11, marginTop: 4 }}>
            Return to Timeline and pull to refresh.
          </Text>
        </View>
      )}

      {/* Results list */}
      <FlatList
        data={results}
        keyExtractor={(item) => item}
        contentContainerStyle={{ paddingTop: 8 }}
        renderItem={({ item }) => (
          <TouchableOpacity
            onPress={() => selectMajor(item)}
            disabled={saving}
            activeOpacity={0.6}
            style={{
              paddingHorizontal: 20,
              paddingVertical: 15,
              borderBottomWidth: 1,
              borderBottomColor: "#f3f4f6",
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Text style={{ color: "#1e293b", fontSize: 13, flex: 1, marginRight: 12 }}>
              {item}
            </Text>
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
