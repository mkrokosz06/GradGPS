import React, { useMemo, useState } from "react";
import { View, Text, TouchableOpacity, Linking, ActivityIndicator } from "react-native";
import type {
  EntranceToMajor,
  EntranceGroup,
  TimelineData,
  TimelineCourse,
} from "../services/timelineService";
import { putChoice, deleteChoice } from "../services/userChoicesService";

/**
 * Entrance to Major — the gate a student must clear to be admitted to their major.
 *
 * Deliberately a checklist and nothing more. Every course here is ALREADY a
 * requirement of the major, so this screen adds no work to the plan; it says
 * which of those courses have a deadline attached, at what grade, and behind
 * what GPA.
 *
 * Choosing a course writes an ordinary `user_course_choices` row against the
 * slot the timeline already emits for that requirement — the same row the pool
 * dropdown writes. That is what makes the pick show up in the plan without
 * scheduling a second copy of the course.
 *
 * The semester is optional on purpose: most students want to say "I'll take
 * CYBER 100" without committing to when, and the packer places it.
 */

const DOT: Record<string, { mark: string; color: string }> = {
  done:        { mark: "✓", color: "#16a34a" },
  in_progress: { mark: "→", color: "#d97706" },
  below_grade: { mark: "!", color: "#dc2626" },
  partial:     { mark: "◐", color: "#d97706" },
  missing:     { mark: "○", color: "#cbd5e1" },
};

/** "IST 242 or CMPSC 122" — a branch's codes joined, then branches by "or". */
function groupLabel(group: EntranceGroup): string {
  return group.branches
    .map((b) => b.codes.join(" + "))
    .join("  or  ");
}

function requirementLine(gate: EntranceToMajor): string | null {
  const parts: string[] = [];
  if (gate.min_grade) parts.push(`${gate.min_grade} or better in each`);
  if (gate.gpa_min) parts.push(`${gate.gpa_min.toFixed(2)} GPA`);
  if (gate.semester_standing) parts.push(`by semester ${gate.semester_standing}`);
  return parts.length ? parts.join(" · ") : null;
}

export function EntranceToMajorCard({
  gate,
  timeline,
  userId,
  onChanged,
}: {
  gate: EntranceToMajor;
  timeline: TimelineData | null;
  userId: string;
  onChanged: () => void;
}) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  /** What the plan currently shows for each slot, so the card can reflect a
   *  pick the student already made (here or from the timeline screen). */
  const bySlot = useMemo(() => {
    const map = new Map<string, { course: TimelineCourse; term: string }>();
    for (const sem of timeline?.semesters ?? []) {
      for (const c of sem.courses ?? []) {
        if (c.slot_key) map.set(c.slot_key, { course: c, term: sem.term });
      }
    }
    return map;
  }, [timeline]);

  /** Upcoming terms the student can pin to. Taken from the plan itself so the
   *  options are always terms that actually exist in it. */
  const terms = useMemo(
    () =>
      (timeline?.semesters ?? [])
        .filter((s) => s.status === "upcoming")
        .map((s) => ({ term: s.term, label: s.label })),
    [timeline],
  );

  const unmet = gate.groups.filter((g) => g.status !== "done");
  const met = gate.groups.filter((g) => g.status === "done");

  async function choose(group: EntranceGroup, code: string | null) {
    if (!group.slot_key || !group.slot_kind) return;
    setSaving(group.slot_key);
    try {
      const current = bySlot.get(group.slot_key);
      const pinned = current?.course.pinned ? current.term : undefined;
      if (code === null && !pinned) {
        await deleteChoice(userId, group.slot_key);
      } else {
        await putChoice(userId, {
          slot_key:  group.slot_key,
          slot_kind: group.slot_kind,
          ...(code ? { chosen_course: code } : {}),
          ...(pinned ? { pinned_term: pinned } : {}),
        });
      }
      onChanged();
    } finally {
      setSaving(null);
    }
  }

  async function pin(group: EntranceGroup, term: string | null) {
    if (!group.slot_key || !group.slot_kind) return;
    setSaving(group.slot_key);
    try {
      const current = bySlot.get(group.slot_key);
      const chosen = current?.course.chosen_code ?? undefined;
      if (term === null && !chosen) {
        await deleteChoice(userId, group.slot_key);
      } else {
        await putChoice(userId, {
          slot_key:  group.slot_key,
          slot_kind: group.slot_kind,
          ...(chosen ? { chosen_course: chosen } : {}),
          ...(term ? { pinned_term: term } : {}),
        });
      }
      onChanged();
    } finally {
      setSaving(null);
    }
  }

  return (
    <View
      style={{
        backgroundColor: "#f0f4ff",
        borderRadius: 16,
        padding: 18,
        borderWidth: 1,
        borderColor: "#dbeafe",
        marginBottom: 16,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 5 }}>
        <Text
          style={{
            color: "#94a3b8", fontSize: 11, fontWeight: "700",
            letterSpacing: 0.8, flex: 1,
          }}
        >
          ENTRANCE TO MAJOR
        </Text>
        {gate.groups_total > 0 && (
          <Text style={{ color: "#64748b", fontSize: 11, fontWeight: "600" }}>
            {gate.groups_done} of {gate.groups_total} done
          </Text>
        )}
      </View>

      {requirementLine(gate) && (
        <Text style={{ color: "#64748b", fontSize: 12, lineHeight: 17, marginBottom: 10 }}>
          Requires {requirementLine(gate)}.
        </Text>
      )}

      {gate.groups.length === 0 && (
        <Text style={{ color: "#64748b", fontSize: 12, lineHeight: 17, marginBottom: 4 }}>
          No specific courses are required for entrance to this major.
        </Text>
      )}

      {/* Unmet first — which ones you still owe is the point, not the count. */}
      {[...unmet, ...met].map((group, i) => {
        const key = group.slot_key ?? `g${i}`;
        const dot = DOT[group.status] ?? DOT.missing;
        const current = group.slot_key ? bySlot.get(group.slot_key) : undefined;
        const chosen = current?.course.chosen_code;
        const pinnedTerm = current?.course.pinned ? current.term : null;
        const canChoose = (group.choosable?.length ?? 0) > 1;
        const canAct = !!group.slot_key && (canChoose || terms.length > 0);
        const open = openKey === key;

        return (
          <View
            key={key}
            style={{
              paddingVertical: 9,
              borderBottomWidth: 1,
              borderBottomColor: "#e0e9ff",
            }}
          >
            <TouchableOpacity
              disabled={!canAct}
              onPress={() => setOpenKey(open ? null : key)}
              style={{ flexDirection: "row", alignItems: "center" }}
            >
              <Text style={{ color: dot.color, fontSize: 14, width: 20, fontWeight: "700" }}>
                {dot.mark}
              </Text>
              <View style={{ flex: 1, marginRight: 8 }}>
                <Text
                  style={{
                    color: group.status === "done" ? "#94a3b8" : "#1e293b",
                    fontSize: 13,
                    fontWeight: "600",
                  }}
                >
                  {chosen ?? groupLabel(group)}
                </Text>
                {group.status === "below_grade" && (
                  <Text style={{ color: "#dc2626", fontSize: 11, marginTop: 2 }}>
                    Taken, but below the required grade
                  </Text>
                )}
                {pinnedTerm && (
                  <Text style={{ color: "#64748b", fontSize: 11, marginTop: 2 }}>
                    Planned for {current?.course ? pinnedTermLabel(terms, pinnedTerm) : pinnedTerm}
                  </Text>
                )}
              </View>
              {saving === group.slot_key ? (
                <ActivityIndicator size="small" color="#94a3b8" />
              ) : canAct ? (
                <Text style={{ color: "#94a3b8", fontSize: 12 }}>{open ? "▾" : "›"}</Text>
              ) : null}
            </TouchableOpacity>

            {open && (
              <View style={{ marginTop: 8, marginLeft: 20 }}>
                {canChoose && (
                  <>
                    <Text style={LABEL}>WHICH CLASS</Text>
                    <View style={CHIP_ROW}>
                      {group.choosable!.map((code) => (
                        <Chip
                          key={code}
                          label={code}
                          active={chosen === code}
                          onPress={() => choose(group, chosen === code ? null : code)}
                        />
                      ))}
                    </View>
                  </>
                )}

                {terms.length > 0 && (
                  <>
                    <Text style={LABEL}>WHEN (OPTIONAL)</Text>
                    <View style={CHIP_ROW}>
                      <Chip
                        label="GradGPS decides"
                        active={!pinnedTerm}
                        onPress={() => pin(group, null)}
                      />
                      {terms.map((t) => (
                        <Chip
                          key={t.term}
                          label={t.label}
                          active={pinnedTerm === t.term}
                          onPress={() => pin(group, pinnedTerm === t.term ? null : t.term)}
                        />
                      ))}
                    </View>
                  </>
                )}
              </View>
            )}
          </View>
        );
      })}

      {/* PSU states something we cannot check. Never imply we did — quote it and
          send the student to the bulletin. */}
      {gate.needs_confirmation && (
        <View
          style={{
            marginTop: 12, padding: 12, borderRadius: 10,
            backgroundColor: "#fffbeb", borderWidth: 1, borderColor: "#fde68a",
          }}
        >
          <Text style={{ color: "#92400e", fontSize: 11, fontWeight: "700", letterSpacing: 0.6 }}>
            CONFIRM WITH YOUR ADVISER
          </Text>
          {gate.notes.slice(0, 2).map((note, i) => (
            <Text
              key={i}
              style={{ color: "#78350f", fontSize: 12, lineHeight: 17, marginTop: 6 }}
            >
              “{note.length > 220 ? `${note.slice(0, 220).trim()}…` : note}”
            </Text>
          ))}
          <Text style={{ color: "#92400e", fontSize: 11, lineHeight: 16, marginTop: 6 }}>
            GradGPS can’t check this part for you.
          </Text>
          {gate.source_url && (
            <TouchableOpacity onPress={() => Linking.openURL(gate.source_url!)}>
              <Text
                style={{
                  color: "#b45309", fontSize: 12, fontWeight: "600", marginTop: 8,
                }}
              >
                View on the PSU bulletin →
              </Text>
            </TouchableOpacity>
          )}
        </View>
      )}
    </View>
  );
}

function pinnedTermLabel(
  terms: { term: string; label: string }[],
  term: string,
): string {
  return terms.find((t) => t.term === term)?.label ?? term;
}

const LABEL = {
  color: "#94a3b8" as const,
  fontSize: 10,
  fontWeight: "700" as const,
  letterSpacing: 0.7,
  marginBottom: 6,
  marginTop: 4,
};

const CHIP_ROW = {
  flexDirection: "row" as const,
  flexWrap: "wrap" as const,
  gap: 6,
  marginBottom: 6,
};

function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <TouchableOpacity
      onPress={onPress}
      style={{
        paddingHorizontal: 10,
        paddingVertical: 6,
        borderRadius: 999,
        backgroundColor: active ? "#1a3a6b" : "#ffffff",
        borderWidth: 1,
        borderColor: active ? "#1a3a6b" : "#dbeafe",
      }}
    >
      <Text
        style={{
          color: active ? "#ffffff" : "#1e293b",
          fontSize: 12,
          fontWeight: "600",
        }}
      >
        {label}
      </Text>
    </TouchableOpacity>
  );
}
