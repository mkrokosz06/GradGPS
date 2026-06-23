import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import axios from "axios";
import { API_BASE, USER_ID } from "../../constants/api";

// ── Types ────────────────────────────────────────────────────────────────────

type CourseItem = {
  course_code: string;
  course_title: string;
  credits: number | null;
  status: "done" | "in_progress" | "missing";
  grade: string;
  pair_group_id?: string;
  pair_status?: string;
  multi_category?: boolean;
};

type Group = {
  name: string;
  group_type: string;
  threshold: number | null;
  satisfied: boolean;
  done: number;
  in_progress: number;
  missing: number;
  credits_earned: number;
  sub_groups?: Array<{
    sub_type: string;
    threshold: number | null;
    satisfied: boolean;
    done: number;
    in_progress: number;
    missing: number;
    credits_earned: number;
    items: CourseItem[];
  }>;
  items: CourseItem[];
};

type AuditSection = {
  major: string;
  total: number;
  done: number;
  in_progress: number;
  missing: number;
  credits_earned: number;
  groups: Group[];
};

type AuditResult = AuditSection & {
  subplan: string | null;
  transcript_credits: number;
  gen_ed?: AuditSection | null;
};

// ── Small components ─────────────────────────────────────────────────────────

function Stat({ value, label, color }: { value: number | string; label: string; color: string }) {
  return (
    <View className="items-center">
      <Text className={`text-2xl font-bold ${color}`}>{value}</Text>
      <Text className="text-xs text-slate-400">{label}</Text>
    </View>
  );
}

function ProgressRing({ done, inProgress, total }: { done: number; inProgress: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <View className="items-center py-4">
      <View className="w-32 h-32 rounded-full border-8 border-navy-light items-center justify-center bg-navy">
        <Text className="text-4xl font-bold text-gold">{pct}%</Text>
        <Text className="text-xs text-slate-300">of major</Text>
      </View>
      <View className="flex-row gap-6 mt-4">
        <Stat value={done}                      label="Done"        color="text-done" />
        <Stat value={inProgress}                label="In Progress" color="text-progress" />
        <Stat value={total - done - inProgress} label="Missing"     color="text-missing" />
      </View>
    </View>
  );
}

function CourseRow({ item }: { item: CourseItem }) {
  const bg:  Record<string, string> = { done: "bg-done/20 border-done", in_progress: "bg-progress/20 border-progress", missing: "bg-missing/10 border-missing/30" };
  const dot: Record<string, string> = { done: "✓", in_progress: "→", missing: "○" };
  const tc:  Record<string, string> = { done: "text-done", in_progress: "text-progress", missing: "text-slate-400" };

  return (
    <View className={`flex-row items-center px-3 py-2 mb-1 rounded-lg border ${bg[item.status] ?? "bg-slate-800 border-slate-700"}`}>
      <Text className={`w-6 text-center font-bold ${tc[item.status]}`}>{dot[item.status]}</Text>
      <View className="flex-1 ml-2">
        <Text className="text-white font-medium text-sm">
          {item.course_code}{item.multi_category ? " ★" : ""}
        </Text>
        {item.course_title ? <Text className="text-slate-400 text-xs" numberOfLines={1}>{item.course_title}</Text> : null}
      </View>
      {item.grade ? <Text className="text-slate-300 text-xs ml-2">{item.grade}</Text> : null}
    </View>
  );
}

// Renders a pair of alternative courses: satisfied pairs show only the taken
// course; unsatisfied pairs show both options with an "OR" divider.
function PairRow({ items }: { items: CourseItem[] }) {
  const pairStatus = items[0]?.pair_status;

  if (pairStatus === "done" || pairStatus === "in_progress") {
    // Show only the course that satisfies the pair
    const winner = items.find(i => i.status === "done" || i.status === "in_progress") ?? items[0];
    return <CourseRow item={winner} />;
  }

  // Both options missing — show them stacked with an OR badge
  return (
    <View className="mb-1 rounded-lg border border-missing/30 overflow-hidden">
      {items.map((item, idx) => (
        <View key={item.course_code}>
          <View className="flex-row items-center px-3 py-2">
            <Text className="w-6 text-center font-bold text-slate-400">○</Text>
            <View className="flex-1 ml-2">
              <Text className="text-white font-medium text-sm">{item.course_code}</Text>
              {item.course_title ? <Text className="text-slate-400 text-xs" numberOfLines={1}>{item.course_title}</Text> : null}
            </View>
          </View>
          {idx < items.length - 1 && (
            <View className="flex-row items-center">
              <View className="flex-1 h-px bg-slate-700 ml-10" />
              <View className="bg-slate-700 px-2 py-0.5 rounded-full mx-2">
                <Text className="text-slate-400 text-xs font-bold">OR</Text>
              </View>
              <View className="flex-1 h-px bg-slate-700 mr-3" />
            </View>
          )}
        </View>
      ))}
    </View>
  );
}

// ── Choose-credits pool (smarter display) ─────────────────────────────────────
// Only shows done/in_progress items prominently.
// Missing options are collapsed behind "Show X more options".

function CreditsPool({
  items, threshold, satisfied, creditsEarned,
}: {
  items: CourseItem[];
  threshold: number | null;
  satisfied: boolean;
  creditsEarned: number;
}) {
  const [showAll, setShowAll] = useState(false);

  const active  = items.filter(i => i.status !== "missing");
  const options = items.filter(i => i.status === "missing");

  const thr = threshold ?? 0;
  const needed = Math.max(0, thr - creditsEarned);

  return (
    <View className="mb-2">
      {/* Status bar */}
      <View className="flex-row items-center mb-2 px-1">
        {satisfied ? (
          <View className="bg-done/20 px-3 py-1 rounded-full">
            <Text className="text-done text-xs font-bold">✓ Requirement met</Text>
          </View>
        ) : (
          <View className="bg-progress/20 px-3 py-1 rounded-full">
            <Text className="text-progress text-xs font-bold">
              Need {needed} more credit{needed !== 1 ? "s" : ""} from options below
            </Text>
          </View>
        )}
      </View>

      {/* Active courses (done / in_progress) */}
      {active.map((item, i) => <CourseRow key={i} item={item} />)}

      {/* Collapsed options */}
      {!satisfied && options.length > 0 && (
        <>
          <TouchableOpacity
            onPress={() => setShowAll(v => !v)}
            className="flex-row items-center mt-1 mb-1"
          >
            <Text className="text-slate-400 text-xs">
              {showAll ? "▲ Hide options" : `▼ Show ${options.length} options`}
            </Text>
          </TouchableOpacity>
          {showAll && options.map((item, i) => <CourseRow key={i} item={item} />)}
        </>
      )}
    </View>
  );
}

// ── Group card ────────────────────────────────────────────────────────────────

function GroupCard({ group }: { group: Group }) {
  const [expanded, setExpanded] = useState(!group.satisfied && group.missing > 0);

  // For mixed groups (choose_one + choose_credits), split rendering
  const hasSubs = group.group_type === "mixed" && group.sub_groups && group.sub_groups.length > 0;

  // For homogeneous groups — deduplicate pairs
  const allItems = group.items ?? [];
  const seen = new Set<string>();
  const displayItems: CourseItem[] = [];
  for (const item of allItems) {
    if (item.pair_group_id) {
      const key = `pair_${item.pair_group_id}`;
      if (seen.has(key)) continue;
      if (item.pair_status === "done" && item.status !== "done") continue;
      seen.add(key);
    }
    displayItems.push(item);
  }

  return (
    <View className="mb-3 rounded-xl overflow-hidden border border-slate-700">
      <TouchableOpacity
        className="flex-row items-center justify-between px-4 py-3 bg-navy-light/40"
        onPress={() => setExpanded(e => !e)}
        activeOpacity={0.7}
      >
        <View className="flex-1">
          <Text className="text-white font-semibold text-sm" numberOfLines={2}>{group.name}</Text>
          <Text className="text-slate-400 text-xs mt-0.5">
            {group.done} done · {group.in_progress} in progress · {group.missing} needed
          </Text>
        </View>
        <View className="ml-3 flex-row items-center gap-2">
          {group.satisfied && (
            <View className="bg-done/20 px-2 py-0.5 rounded-full">
              <Text className="text-done text-xs font-bold">✓</Text>
            </View>
          )}
          <Text className="text-slate-400 text-base">{expanded ? "▲" : "▼"}</Text>
        </View>
      </TouchableOpacity>

      {expanded && (
        <View className="px-3 py-2 bg-slate-900">
          {hasSubs ? (
            // Mixed group: render each sub-group with appropriate display
            group.sub_groups!.map((sg, si) => (
              <View key={si} className="mb-3">
                {sg.sub_type === "choose_credits" ? (
                  <>
                    <Text className="text-slate-500 text-xs uppercase tracking-wide mb-1 ml-1">
                      Elective pool — pick {sg.threshold} credits
                    </Text>
                    <CreditsPool
                      items={sg.items}
                      threshold={sg.threshold}
                      satisfied={sg.satisfied}
                      creditsEarned={sg.credits_earned}
                    />
                  </>
                ) : (
                  // choose_one items — group pairs together, individuals as-is
                  (() => {
                    const pairMap = new Map<string, CourseItem[]>();
                    const order: Array<{ type: "pair"; id: string } | { type: "single"; item: CourseItem }> = [];
                    for (const item of sg.items) {
                      if (item.pair_group_id) {
                        const k = item.pair_group_id;
                        if (!pairMap.has(k)) {
                          pairMap.set(k, []);
                          order.push({ type: "pair", id: k });
                        }
                        pairMap.get(k)!.push(item);
                      } else {
                        order.push({ type: "single", item });
                      }
                    }
                    return order.map((entry, i) =>
                      entry.type === "pair"
                        ? <PairRow key={`pair_${entry.id}`} items={pairMap.get(entry.id)!} />
                        : <CourseRow key={`${entry.item.course_code}_${i}`} item={entry.item} />
                    );
                  })()
                )}
              </View>
            ))
          ) : group.group_type === "choose_credits" ? (
            <CreditsPool
              items={displayItems}
              threshold={group.threshold}
              satisfied={group.satisfied}
              creditsEarned={group.credits_earned}
            />
          ) : (
            // Build pair-aware render list for choose_one / required groups
            (() => {
              const pairMap = new Map<string, CourseItem[]>();
              const order: Array<{ type: "pair"; id: string } | { type: "single"; item: CourseItem }> = [];
              for (const item of allItems) {
                if (item.pair_group_id) {
                  const k = item.pair_group_id;
                  if (!pairMap.has(k)) { pairMap.set(k, []); order.push({ type: "pair", id: k }); }
                  pairMap.get(k)!.push(item);
                } else {
                  order.push({ type: "single", item });
                }
              }
              return order.map((entry, i) =>
                entry.type === "pair"
                  ? <PairRow key={`pair_${entry.id}`} items={pairMap.get(entry.id)!} />
                  : <CourseRow key={`${entry.item.course_code}_${i}`} item={entry.item} />
              );
            })()
          )}
        </View>
      )}
    </View>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export default function AuditScreen() {
  const [audit, setAudit]           = useState<AuditResult | null>(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab]   = useState<"major" | "gen_ed">("major");

  const fetchAudit = useCallback(async () => {
    try {
      const res = await axios.get<AuditResult>(`${API_BASE}/audit`, {
        headers: { "x-user-id": USER_ID },
      });
      setAudit(res.data);
      setError(null);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "Could not load audit. Is the backend running?");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchAudit(); }, [fetchAudit]);
  const onRefresh = useCallback(() => { setRefreshing(true); fetchAudit(); }, [fetchAudit]);

  if (loading) {
    return (
      <SafeAreaView className="flex-1 bg-navy items-center justify-center">
        <ActivityIndicator size="large" color="#E8C84B" />
        <Text className="text-slate-400 mt-3">Loading audit…</Text>
      </SafeAreaView>
    );
  }

  if (error) {
    return (
      <SafeAreaView className="flex-1 bg-navy items-center justify-center px-8">
        <Text className="text-4xl mb-4">⚠️</Text>
        <Text className="text-white text-center font-semibold">{error}</Text>
        <TouchableOpacity onPress={fetchAudit} className="mt-6 bg-gold px-6 py-3 rounded-xl">
          <Text className="text-navy font-bold">Retry</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  if (!audit) return null;

  const section  = activeTab === "gen_ed" && audit.gen_ed ? audit.gen_ed : audit;
  const hasGenEd = !!audit.gen_ed;

  return (
    <SafeAreaView className="flex-1 bg-navy">
      <ScrollView
        className="flex-1"
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#E8C84B" />}
        contentContainerStyle={{ paddingBottom: 32 }}
      >
        {/* Header */}
        <View className="px-5 pt-4 pb-1">
          <Text className="text-gold font-bold text-2xl">GradGPS</Text>
          <Text className="text-white text-sm mt-1" numberOfLines={2}>{audit.major}</Text>
          {audit.subplan ? <Text className="text-slate-400 text-xs">{audit.subplan}</Text> : null}
        </View>

        {/* Credits banner */}
        <View className="mx-5 mt-3 mb-1 bg-navy-light/25 rounded-xl px-4 py-3 flex-row justify-between items-center border border-slate-700">
          <View>
            <Text className="text-white font-bold text-lg">{audit.transcript_credits} cr</Text>
            <Text className="text-slate-400 text-xs">earned toward 120 needed</Text>
          </View>
          <View className="items-end">
            <Text className="text-gold font-bold text-lg">{Math.round((audit.transcript_credits / 120) * 100)}%</Text>
            <Text className="text-slate-400 text-xs">credit progress</Text>
          </View>
        </View>

        {/* Tab switcher */}
        {hasGenEd && (
          <View className="flex-row mx-5 mt-3 bg-navy-light/20 rounded-xl p-1">
            {(["major", "gen_ed"] as const).map(tab => (
              <TouchableOpacity
                key={tab}
                onPress={() => setActiveTab(tab)}
                className={`flex-1 py-2 rounded-lg items-center ${activeTab === tab ? "bg-navy-light" : ""}`}
              >
                <Text className={`text-sm font-semibold ${activeTab === tab ? "text-gold" : "text-slate-400"}`}>
                  {tab === "major" ? "Major" : "Gen Ed"}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        )}

        {/* Progress ring — major requirement slots */}
        <ProgressRing done={section.done} inProgress={section.in_progress} total={section.total} />

        {/* Groups */}
        <View className="px-4">
          <Text className="text-slate-400 text-xs uppercase tracking-widest mb-3">
            {activeTab === "major" ? "Major Requirements" : "General Education"}
          </Text>
          {section.groups.map((group, i) => (
            <GroupCard key={i} group={group} />
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
