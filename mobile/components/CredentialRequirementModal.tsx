import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, TouchableOpacity, Modal, FlatList, ActivityIndicator, Dimensions,
} from "react-native";
import { useAuth } from "../context/AuthContext";
import {
  getCredentialChoices, addCredentialChoice, removeCredentialChoice,
  requirementKey, credentialChoiceError,
} from "../services/credentialChoiceService";
import { getTranscript, type TranscriptCourse } from "../services/transcriptService";

const WIN_H  = Dimensions.get("window").height;
const LIST_H = Math.round(WIN_H * 0.32);

type Chosen = { course_code: string; credits: number; grade: string; status: string };

/**
 * "Which courses are you using for this?"
 *
 * Some PSU minors state a requirement the bulletin never resolves into a course list
 * — "Select 6 credits from an approved list in consultation with the minor adviser".
 * There is no rule to evaluate, so `_eval_unstructured_credits` never satisfies one on
 * its own; without this the credential could never read as complete.
 *
 * Three things this screen has to get right:
 *   - the bulletin's wording is quoted verbatim, because the student is going to take
 *     it to an adviser and a paraphrase is useless for that conversation;
 *   - progress is a meter, not a checkbox — partial is the honest state most students
 *     are in, and the backend counts real credits;
 *   - it reads as the student's own claim, not something GradGPS approved.
 *
 * Only courses already on the transcript can be added (the backend enforces it too),
 * which is what keeps the credit count real rather than a guess about a future course.
 */
export function CredentialRequirementModal({
  visible,
  program,
  requirementGroup,
  requirementText,
  threshold,
  onSaved,
  onClose,
}: {
  visible: boolean;
  program: string | null;
  requirementGroup: string | null;
  /** The bulletin sentence, shown verbatim. */
  requirementText?: string;
  /** Credits the requirement asks for. */
  threshold: number;
  /** Called after any change so the caller can refetch audit/timeline. */
  onSaved: () => void | Promise<void>;
  onClose: () => void;
}) {
  const { userId } = useAuth();
  const [loading, setLoading]   = useState(false);
  const [busy, setBusy]         = useState(false);
  const [error, setError]       = useState("");
  const [chosen, setChosen]     = useState<Chosen[]>([]);
  const [available, setAvailable] = useState<TranscriptCourse[]>([]);
  const [adding, setAdding]     = useState(false);

  const load = useCallback(async () => {
    if (!userId || !program || !requirementGroup) return;
    setLoading(true);
    setError("");
    try {
      const [choices, transcript] = await Promise.all([
        getCredentialChoices(userId),
        getTranscript(userId),
      ]);
      const codes = choices[requirementKey(program, requirementGroup)] ?? [];
      const all: TranscriptCourse[] = transcript.terms.flatMap((t) => t.courses);
      const byCode = new Map(all.map((c) => [c.course_code, c]));
      setChosen(codes.map((code) => ({
        course_code: code,
        credits: byCode.get(code)?.credits_earned ?? 3,
        grade:   byCode.get(code)?.grade ?? "",
        status:  byCode.get(code)?.status ?? "done",
      })));
      // Offer only courses not already used for this requirement.
      setAvailable(all.filter((c) => !codes.includes(c.course_code)));
    } catch (e) {
      setError(credentialChoiceError(e));
    } finally {
      setLoading(false);
    }
  }, [userId, program, requirementGroup]);

  useEffect(() => {
    if (visible) { setAdding(false); load(); }
  }, [visible, load]);

  const earned = useMemo(
    () => chosen.reduce((n, c) => n + (c.credits || 0), 0),
    [chosen],
  );
  const pct = threshold > 0 ? Math.min(100, Math.round((earned / threshold) * 100)) : 0;
  const done = threshold > 0 && earned >= threshold;

  async function add(code: string) {
    if (!userId || !program || !requirementGroup) return;
    setBusy(true); setError("");
    try {
      await addCredentialChoice(userId, program, requirementGroup, code);
      setAdding(false);
      await load();
      await onSaved();
    } catch (e) {
      setError(credentialChoiceError(e));
    } finally { setBusy(false); }
  }

  async function remove(code: string) {
    if (!userId || !program || !requirementGroup) return;
    setBusy(true); setError("");
    try {
      await removeCredentialChoice(userId, program, requirementGroup, code);
      await load();
      await onSaved();
    } catch (e) {
      setError(credentialChoiceError(e));
    } finally { setBusy(false); }
  }

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(15,23,42,0.35)" }}>
        <View style={{
          backgroundColor: "#ffffff",
          borderTopLeftRadius: 20, borderTopRightRadius: 20,
          paddingTop: 18, paddingBottom: 28, paddingHorizontal: 20,
        }}>
          {/* Header */}
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
            <View style={{ flex: 1, marginRight: 10 }}>
              <Text style={{ color: "#0f172a", fontSize: 17, fontWeight: "700" }}>
                {program ?? ""}
              </Text>
              <Text style={{ color: "#94a3b8", fontSize: 11.5, marginTop: 2 }}>
                Choose the courses you're using
              </Text>
            </View>
            <TouchableOpacity onPress={onClose} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
              <Text style={{ color: "#94a3b8", fontSize: 20 }}>×</Text>
            </TouchableOpacity>
          </View>

          {/* The bulletin's own words — quoted, because this is what the adviser
              conversation is actually about. */}
          {requirementText ? (
            <View style={{
              marginTop: 14, padding: 12, borderRadius: 12,
              backgroundColor: "#f8fafc", borderLeftWidth: 3, borderLeftColor: "#cbd5e1",
            }}>
              <Text style={{ color: "#334155", fontSize: 12.5, lineHeight: 18, fontStyle: "italic" }}>
                “{requirementText}”
              </Text>
              <Text style={{ color: "#94a3b8", fontSize: 10.5, marginTop: 6 }}>
                — Penn State bulletin
              </Text>
            </View>
          ) : null}

          {/* Credit meter */}
          <View style={{ marginTop: 16 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 6 }}>
              <Text style={{ color: "#64748b", fontSize: 12, fontWeight: "600" }}>
                {done ? "Requirement met" : "Credits chosen"}
              </Text>
              <Text style={{ color: done ? "#16a34a" : "#1a3a6b", fontSize: 12.5, fontWeight: "700" }}>
                {earned} of {threshold} credits
              </Text>
            </View>
            <View style={{ height: 8, backgroundColor: "#f1f5f9", borderRadius: 4, overflow: "hidden" }}>
              <View style={{
                height: "100%", width: `${pct}%`,
                backgroundColor: done ? "#16a34a" : "#1a3a6b", borderRadius: 4,
              }} />
            </View>
          </View>

          {loading ? (
            <View style={{ paddingVertical: 24, alignItems: "center" }}>
              <ActivityIndicator color="#1a3a6b" />
            </View>
          ) : adding ? (
            /* Pick from the student's own transcript. Only real, earned courses —
               that is what keeps the credit total honest. */
            <View style={{ marginTop: 14 }}>
              <Text style={{ color: "#64748b", fontSize: 12, fontWeight: "600", marginBottom: 6 }}>
                YOUR COURSES
              </Text>
              <FlatList
                style={{ height: LIST_H }}
                data={available}
                keyExtractor={(c) => c.course_code}
                keyboardShouldPersistTaps="handled"
                renderItem={({ item }) => (
                  <TouchableOpacity
                    disabled={busy}
                    onPress={() => add(item.course_code)}
                    activeOpacity={0.6}
                    style={{
                      flexDirection: "row", alignItems: "center",
                      paddingVertical: 12,
                      borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
                    }}
                  >
                    <Text style={{ color: "#1e293b", fontSize: 13.5, flex: 1 }}>
                      {item.course_code}
                    </Text>
                    <Text style={{ color: "#94a3b8", fontSize: 11.5, marginRight: 10 }}>
                      {item.credits_earned} cr
                      {item.status === "in_progress" ? " · in progress" : ""}
                    </Text>
                    <Text style={{ color: "#1a3a6b", fontSize: 12.5, fontWeight: "700" }}>Add</Text>
                  </TouchableOpacity>
                )}
                ListEmptyComponent={
                  <View style={{ alignItems: "center", paddingTop: 28 }}>
                    <Text style={{ color: "#cbd5e1", fontSize: 12.5, textAlign: "center" }}>
                      No other courses on your transcript yet.{"\n"}
                      Add them here once you've taken them.
                    </Text>
                  </View>
                }
              />
              <TouchableOpacity onPress={() => setAdding(false)} style={{ paddingTop: 10 }}>
                <Text style={{ color: "#94a3b8", fontSize: 12.5 }}>Cancel</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={{ marginTop: 14 }}>
              {chosen.map((c) => (
                <View
                  key={c.course_code}
                  style={{
                    flexDirection: "row", alignItems: "center",
                    paddingVertical: 11,
                    borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
                  }}
                >
                  <Text style={{ color: "#1e293b", fontSize: 13.5, flex: 1 }}>{c.course_code}</Text>
                  <Text style={{ color: "#94a3b8", fontSize: 11.5, marginRight: 12 }}>
                    {c.credits} cr
                  </Text>
                  <TouchableOpacity
                    onPress={() => remove(c.course_code)}
                    disabled={busy}
                    hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                  >
                    <Text style={{ color: "#94a3b8", fontSize: 16 }}>×</Text>
                  </TouchableOpacity>
                </View>
              ))}

              {chosen.length === 0 ? (
                <Text style={{ color: "#94a3b8", fontSize: 12.5, paddingVertical: 8 }}>
                  Nothing chosen yet.
                </Text>
              ) : null}

              <TouchableOpacity
                onPress={() => setAdding(true)}
                disabled={busy}
                style={{ paddingTop: 14 }}
              >
                <Text style={{ color: "#1a3a6b", fontSize: 13.5, fontWeight: "700" }}>
                  {busy ? "Saving…" : "+ Add a course"}
                </Text>
              </TouchableOpacity>
            </View>
          )}

          {error ? (
            <Text style={{ color: "#ef4444", fontSize: 12, marginTop: 12, lineHeight: 17 }}>
              {error}
            </Text>
          ) : null}

          {/* The student's claim, not an approved exception — same framing the
              substitution flow uses. */}
          <Text style={{ color: "#94a3b8", fontSize: 11, marginTop: 16, lineHeight: 16 }}>
            You're telling GradGPS these count. Your adviser has the final say.
          </Text>
        </View>
      </View>
    </Modal>
  );
}
