import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, Modal, FlatList,
  ActivityIndicator, Dimensions,
} from "react-native";
import {
  searchCredentials, creditLabel,
  type CredentialSummary,
} from "../services/credentialService";
import { useAuth } from "../context/AuthContext";

const WIN_H  = Dimensions.get("window").height;
const LIST_H = Math.round(WIN_H * 0.5);

/**
 * "Add a minor or certificate."
 *
 * A modal rather than a route: the tab bar is hidden (see app/(tabs)/_layout.tsx)
 * and this is a sub-flow of Account, so pushing a screen would strand the user
 * without a back affordance.
 *
 * Search mirrors app/(tabs)/major.tsx — full list up front, filtered client-side —
 * because the catalog is ~200 entries and fits in one fetch.
 */
export function CredentialPickerModal({
  visible,
  alreadyDeclared,
  onPick,
  onClose,
}: {
  visible: boolean;
  /** Program names already declared, so they can be shown as added. */
  alreadyDeclared: string[];
  onPick: (programName: string) => void | Promise<void>;
  onClose: () => void;
}) {
  const { userId } = useAuth();
  const [all, setAll]         = useState<CredentialSummary[]>([]);
  const [query, setQuery]     = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setQuery("");
    setLoading(true);
    searchCredentials(userId!)
      .then(setAll)
      .catch(() => setAll([]))
      .finally(() => setLoading(false));
  }, [visible, userId]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter((c) => c.program_name.toLowerCase().includes(q));
  }, [query, all]);

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(15,23,42,0.35)" }}>
        <View style={{
          backgroundColor: "#ffffff",
          borderTopLeftRadius: 20, borderTopRightRadius: 20,
          paddingTop: 18, paddingBottom: 28, paddingHorizontal: 20,
        }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text style={{ color: "#0f172a", fontSize: 17, fontWeight: "700" }}>
              Add a minor or certificate
            </Text>
            <TouchableOpacity onPress={onClose} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
              <Text style={{ color: "#94a3b8", fontSize: 20 }}>×</Text>
            </TouchableOpacity>
          </View>

          <Text style={{ color: "#64748b", fontSize: 12, marginTop: 6, lineHeight: 17 }}>
            Its remaining courses get added to your timeline.
          </Text>

          <View style={{
            flexDirection: "row", alignItems: "center", marginTop: 14,
            backgroundColor: "#f8fafc", borderRadius: 12,
            borderWidth: 1.5, borderColor: "#e2e8f0", paddingHorizontal: 12,
          }}>
            <Text style={{ color: "#94a3b8", fontSize: 15, marginRight: 8 }}>⌕</Text>
            <TextInput
              style={{ flex: 1, color: "#111827", paddingVertical: 11, fontSize: 14 }}
              placeholder="Search minors and certificates…"
              placeholderTextColor="#94a3b8"
              value={query}
              onChangeText={setQuery}
              autoCapitalize="none"
              returnKeyType="search"
            />
            {loading ? <ActivityIndicator size="small" color="#1a3a6b" /> : null}
          </View>

          <FlatList
            style={{ height: LIST_H, marginTop: 10 }}
            data={results}
            keyExtractor={(item) => item.program_name}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => {
              const added = alreadyDeclared.includes(item.program_name);
              return (
                <TouchableOpacity
                  disabled={added}
                  onPress={() => onPick(item.program_name)}
                  activeOpacity={0.6}
                  style={{
                    paddingVertical: 13, borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
                    flexDirection: "row", alignItems: "center", opacity: added ? 0.45 : 1,
                  }}
                >
                  <View style={{ flex: 1, marginRight: 10 }}>
                    <Text style={{ color: "#1e293b", fontSize: 13.5 }}>{item.program_name}</Text>
                    <Text style={{ color: "#94a3b8", fontSize: 11, marginTop: 2 }}>
                      {creditLabel(item.credits)}
                      {item.manual_credits
                        ? ` · ${item.manual_credits} cr chosen with your adviser`
                        : ""}
                    </Text>
                  </View>
                  <Text style={{
                    color: added ? "#94a3b8" : "#1a3a6b", fontSize: 12.5, fontWeight: "700",
                  }}>
                    {added ? "Added" : "Add"}
                  </Text>
                </TouchableOpacity>
              );
            }}
            ListEmptyComponent={
              loading ? null : (
                <View style={{ alignItems: "center", paddingTop: 36 }}>
                  <Text style={{ color: "#cbd5e1", fontSize: 13 }}>No matches</Text>
                </View>
              )
            }
          />
        </View>
      </View>
    </Modal>
  );
}
