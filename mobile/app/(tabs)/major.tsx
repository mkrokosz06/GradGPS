import React, { useState, useCallback } from "react";
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

export default function MajorScreen() {
  const [query, setQuery]       = useState("");
  const [results, setResults]   = useState<string[]>([]);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving]     = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const search = useCallback(async (q: string) => {
    setQuery(q);
    if (q.trim().length < 2) { setResults([]); return; }
    setSearching(true);
    try {
      const res = await axios.get<{ results: string[] }>(`${API_BASE}/programs/search`, {
        params: { q: q.trim() },
      });
      setResults(res.data.results);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }, []);

  async function selectMajor(major: string) {
    setSaving(true);
    try {
      await axios.post(
        `${API_BASE}/programs/select`,
        { major },
        { headers: { "x-user-id": USER_ID } },
      );
      setSelected(major);
      setResults([]);
      setQuery("");
      Alert.alert("Major saved!", `Switched to:\n${major}\n\nPull to refresh the Audit tab.`);
    } catch (e: any) {
      Alert.alert("Error", e?.response?.data?.detail ?? "Could not save major.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-navy px-5">
      <Text className="text-gold font-bold text-2xl mt-6 mb-2">Choose Major</Text>
      <Text className="text-slate-400 text-sm mb-5">
        Search for your Penn State major to set up your degree audit.
      </Text>

      <View className="flex-row items-center bg-navy-light/30 border border-slate-600 rounded-xl px-4 mb-4">
        <Text className="text-slate-400 mr-2">🔍</Text>
        <TextInput
          className="flex-1 text-white py-3 text-base"
          placeholder="e.g. Enterprise Technology..."
          placeholderTextColor="#64748b"
          value={query}
          onChangeText={search}
          autoCapitalize="none"
          returnKeyType="search"
        />
        {searching && <ActivityIndicator size="small" color="#E8C84B" />}
      </View>

      {selected && (
        <View className="bg-done/10 border border-done/30 rounded-xl px-4 py-3 mb-4">
          <Text className="text-done text-xs font-bold mb-0.5">CURRENT MAJOR</Text>
          <Text className="text-white text-sm">{selected}</Text>
        </View>
      )}

      <FlatList
        data={results}
        keyExtractor={(item) => item}
        renderItem={({ item }) => (
          <TouchableOpacity
            className="py-3 px-4 border-b border-slate-800 active:bg-navy-light/20"
            onPress={() => selectMajor(item)}
            disabled={saving}
          >
            <Text className="text-white text-sm">{item}</Text>
          </TouchableOpacity>
        )}
        ListEmptyComponent={
          query.length >= 2 && !searching ? (
            <Text className="text-slate-500 text-center mt-6">No programs found</Text>
          ) : null
        }
        keyboardShouldPersistTaps="handled"
      />
    </SafeAreaView>
  );
}
