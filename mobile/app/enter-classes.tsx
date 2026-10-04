/**
 * No-transcript mode: the student walks their major's Suggested Academic Plan
 * semester by semester and confirms which classes they took, instead of
 * uploading a PDF. Plan courses start checked (most students roughly follow the
 * plan), so the job is correcting a list, not recalling one from memory.
 *
 * Steps: which semester you're in → one card per past semester → this
 * semester (in progress) → AP / transfer credit → "C or better?" → review.
 * Saving replaces every course (POST /transcript/self-report). Opened with an
 * existing self-reported history, it starts at the review step, pre-filled.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, TouchableOpacity, ScrollView, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useAuth } from "../context/AuthContext";
import { CourseSearchModal } from "../components/CourseSearchModal";
import {
  getWalkthrough, getTranscript, saveSelfReport,
  type Walkthrough, type WalkCourse, type WalkItem, type SelfReportCourse,
} from "../services/transcriptService";

const NAVY = "#1a3a6b";
const MAX_SEMESTERS = 12;

type Card = {
  checked: Record<string, boolean>;           // course slots (default: checked)
  choice:  Record<string, string | null>;     // choice slots -> picked option (default: first)
  open:    Record<string, WalkCourse | null>; // gen-ed / elective slots -> picked course
  extras:  WalkCourse[];                      // "I took something else"
};

/** One row on a semester card. A plan class the student unchecks moves to the
 *  next semester's card under the same id, labelled with where the plan had it. */
type Slot = { id: string; item: WalkItem; movedFrom?: string };

type SearchTarget =
  | { kind: "open"; card: number; slot: string }
  | { kind: "extra"; card: number }
  | { kind: "transfer" };

// ── Term helpers ("FA 2026") ─────────────────────────────────────────────────

function termIndex(t: string): number {
  const [season, year] = t.split(" ");
  return Number(year) * 2 + (season === "FA" ? 1 : 0);
}

function termFromIndex(i: number): string {
  return i % 2 === 1 ? `FA ${(i - 1) / 2}` : `SP ${i / 2}`;
}

function termLabel(t: string): string {
  const [season, year] = t.split(" ");
  return `${season === "FA" ? "Fall" : season === "SP" ? "Spring" : "Summer"} ${year}`;
}

const ORDINAL_WORD = [
  "First", "Second", "Third", "Fourth", "Fifth", "Sixth",
  "Seventh", "Eighth", "Ninth", "Tenth", "Eleventh", "Twelfth",
];
const ORDINAL = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th", "11th", "12th"];

const norm = (code: string) => code.replace(/\s+/g, " ").trim().toUpperCase();
/** Code without a W/H/M/N attribute suffix, so "ETI 300W" matches "ETI 300". */
const baseCode = (code: string) => norm(code).replace(/(\d)[WHMN]$/, "$1");

// ── Card construction ────────────────────────────────────────────────────────

const emptyCard = (): Card => ({ checked: {}, choice: {}, open: {}, extras: [] });

const isChecked = (card: Card, s: Slot) => card.checked[s.id] ?? true;

function choiceOf(card: Card, s: Slot): string | null {
  if (s.item.kind !== "choice") return null;
  return s.id in card.choice ? card.choice[s.id] : (s.item.options[0]?.code ?? null);
}

function slotCodes(item: WalkItem): string[] {
  if (item.kind === "course") return [baseCode(item.code)];
  if (item.kind === "choice") return item.options.map((o) => baseCode(o.code));
  return [];
}

/** Each semester's rows: classes carried over from the semester before (plan
 *  classes the student said they didn't take then), then the plan's own.
 *
 *  A row the student already has is left off entirely: a plan class (or any
 *  option of a "one of these") entered on an earlier card or as transfer credit,
 *  and a list slot ("Pick from the Business Fundamentals list") that a class from
 *  that list, added earlier as an extra or transfer, already fills. Each such
 *  class fills one list slot only. */
function buildSlots(walk: Walkthrough, cards: Card[], terms: string[], transfer: WalkCourse[]): Slot[][] {
  const out: Slot[][] = [];
  let carry: Slot[] = [];
  const taken = new Set(transfer.map((c) => baseCode(c.code)));
  const loose = transfer.map((c) => baseCode(c.code));   // can still fill a list slot
  const useLoose = (codes: string[]) => {
    for (const c of codes) {
      const i = loose.indexOf(c);
      if (i >= 0) loose.splice(i, 1);
    }
  };
  terms.forEach((term, k) => {
    const plan: Slot[] = (walk.semesters[k]?.items ?? []).map((item, i) => ({ id: `p${k}-${i}`, item }));
    const planned = new Set(plan.flatMap((sl) => slotCodes(sl.item)));
    const slots = [...carry.filter((sl) => !slotCodes(sl.item).some((c) => planned.has(c))), ...plan]
      .filter((sl) => {
        const it = sl.item;
        const had = slotCodes(it).filter((c) => taken.has(c));
        if (had.length) { useLoose(had); return false; }
        if (it.kind === "open" && it.fills_from && it.suggested?.length) {
          const list = new Set(it.suggested.map((c) => baseCode(c.code)));
          const hit = loose.find((c) => list.has(c));
          if (hit) { useLoose([hit]); return false; }
        }
        return true;
      });
    out.push(slots);
    const card = cards[k] ?? emptyCard();
    carry = slots
      .filter((sl) => (sl.item.kind === "course" && !isChecked(card, sl))
        || (sl.item.kind === "choice" && choiceOf(card, sl) === null))
      .map((sl) => ({ ...sl, movedFrom: sl.movedFrom ?? term }));
    cardCourses(slots, card).forEach((c) => taken.add(baseCode(c.code)));
    card.extras.forEach((c) => loose.push(baseCode(c.code)));
  });
  return out;
}

/** A card filled from courses already saved for that term. */
function prefilledCard(slots: Slot[], taken: WalkCourse[]): Card {
  const card = emptyCard();
  const left = [...taken];
  const take = (code: string) => {
    const i = left.findIndex((c) => norm(c.code) === norm(code));
    return i >= 0 ? left.splice(i, 1)[0] : null;
  };
  slots.forEach((sl) => {
    const it = sl.item;
    if (it.kind === "course") card.checked[sl.id] = !!take(it.code);
    if (it.kind === "choice") {
      const hit = it.options.find((o) => left.some((c) => norm(c.code) === norm(o.code)));
      if (hit) take(hit.code);
      card.choice[sl.id] = hit ? hit.code : null;
    }
  });
  slots.forEach((sl) => {
    if (sl.item.kind === "open") card.open[sl.id] = left.shift() ?? null;
  });
  card.extras = left;
  return card;
}

function cardCourses(slots: Slot[], card: Card): WalkCourse[] {
  const out: WalkCourse[] = [];
  slots.forEach((sl) => {
    const it = sl.item;
    if (it.kind === "course" && isChecked(card, sl)) out.push(it);
    if (it.kind === "choice") {
      const o = it.options.find((x) => x.code === choiceOf(card, sl));
      if (o) out.push(o);
    }
    if (it.kind === "open" && card.open[sl.id]) {
      const c = card.open[sl.id]!;
      out.push({ ...c, credits: c.credits || it.credits });
    }
  });
  return [...out, ...card.extras];
}

// ── Screen ───────────────────────────────────────────────────────────────────

export default function EnterClassesScreen() {
  const router = useRouter();
  const { from } = useLocalSearchParams<{ from?: string }>();
  const { userId, completeOnboarding } = useAuth();

  const [walk,     setWalk]     = useState<Walkthrough | null>(null);
  const [error,    setError]    = useState<string | null>(null);
  const [semNum,   setSemNum]   = useState<number | null>(null);
  const [cards,    setCards]    = useState<Card[]>([]);
  const [transfer, setTransfer] = useState<WalkCourse[]>([]);
  const [allC,     setAllC]     = useState<boolean | null>(null);
  const [belowC,   setBelowC]   = useState<Record<string, boolean>>({});
  const [step,     setStep]     = useState(0);
  const [search,   setSearch]   = useState<SearchTarget | null>(null);
  const [saving,   setSaving]   = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([getWalkthrough(userId!), getTranscript(userId!).catch(() => null)])
      .then(([w, tx]) => {
        if (!active) return;
        setWalk(w);
        if (tx?.has_transcript && tx.self_reported) prefill(w, tx);
      })
      .catch((e) => {
        const detail = e?.response?.data?.detail;
        if (active) setError(typeof detail === "string" ? detail : "Couldn't load your plan. Try again.");
      });
    return () => { active = false; };
  }, [userId]);

  function prefill(w: Walkthrough, tx: Awaited<ReturnType<typeof getTranscript>>) {
    const byTerm: Record<string, WalkCourse[]> = {};
    const xfer: WalkCourse[] = [];
    const low: Record<string, boolean> = {};
    for (const t of tx.terms) {
      for (const c of t.courses) {
        const course = { code: c.course_code, title: c.course_title ?? "", credits: c.credits_earned };
        if (c.status === "transfer") xfer.push(course);
        else (byTerm[t.term] ??= []).push(course);
        if (c.grade === "D") low[c.course_code] = true;
      }
    }
    const regular = Object.keys(byTerm).filter((t) => /^(FA|SP) \d{4}$/.test(t));
    const earliest = regular.length
      ? Math.min(...regular.map(termIndex))
      : termIndex(w.current_term);
    const n = Math.min(MAX_SEMESTERS, Math.max(1, termIndex(w.current_term) - earliest + 1));
    const terms = termsFor(w.current_term, n);
    setSemNum(n);
    const built: Card[] = [];
    terms.forEach((t, k) => {
      built.push(prefilledCard(buildSlots(w, built, terms.slice(0, k + 1), xfer)[k], byTerm[t] ?? []));
    });
    setCards(built);
    setTransfer(xfer);
    setBelowC(low);
    setAllC(Object.keys(low).length === 0);
    setStep(n + 3);   // review
  }

  function termsFor(current: string, n: number): string[] {
    const end = termIndex(current);
    return Array.from({ length: n }, (_, k) => termFromIndex(end - (n - 1 - k)));
  }

  const terms = useMemo(
    () => (walk && semNum ? termsFor(walk.current_term, semNum) : []),
    [walk, semNum],
  );

  function chooseSemester(n: number) {
    if (n !== semNum) {
      setSemNum(n);
      setCards(Array.from({ length: n }, emptyCard));
    }
    setStep(1);
  }

  const slots = useMemo(
    () => (walk && semNum ? buildSlots(walk, cards, terms, transfer) : []),
    [walk, semNum, cards, terms, transfer],
  );

  function updateCard(k: number, fn: (c: Card) => Card) {
    setCards((cs) => cs.map((c, i) => (i === k ? fn(c) : c)));
  }

  // Every course the student has said they took, in term order, deduped.
  const entries = useMemo(() => {
    if (!walk || !semNum) return [] as (SelfReportCourse & { title: string })[];
    const seen = new Set<string>();
    const out: (SelfReportCourse & { title: string })[] = [];
    const push = (c: WalkCourse, term: string, status: SelfReportCourse["status"]) => {
      const key = norm(c.code);
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ course_code: c.code, term, status, credits: c.credits || undefined, title: c.title });
    };
    transfer.forEach((c) => push(c, "", "transfer"));
    cards.forEach((card, k) => {
      const status = k === semNum - 1 ? "in_progress" : "done";
      cardCourses(slots[k] ?? [], card).forEach((c) => push(c, terms[k], status));
    });
    return out;
  }, [walk, semNum, cards, transfer, terms, slots]);

  const takenCodes = useMemo(() => new Set(entries.map((e) => e.course_code)), [entries]);
  const doneEntries = entries.filter((e) => e.status === "done");

  function onPick(c: WalkCourse) {
    const t = search!;
    setSearch(null);
    if (t.kind === "transfer") setTransfer((x) => [...x, c]);
    else if (t.kind === "extra") updateCard(t.card, (card) => ({ ...card, extras: [...card.extras, c] }));
    else updateCard(t.card, (card) => ({ ...card, open: { ...card.open, [t.slot]: c } }));
  }

  async function save() {
    if (!entries.length) {
      Alert.alert("No classes yet", "Add at least one class before saving.");
      return;
    }
    setSaving(true);
    try {
      await saveSelfReport(userId!, entries.map(({ title, ...e }) => ({
        ...e,
        below_c: e.status === "done" && allC === false && !!belowC[e.course_code],
      })));
      if (from === "onboarding") {
        await completeOnboarding();
        router.replace("/(tabs)/" as any);
      } else {
        router.navigate("/(tabs)/" as any);
      }
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      Alert.alert("Couldn't save", typeof detail === "string" ? detail : "Something went wrong.");
    } finally {
      setSaving(false);
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  if (error) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: "#ffffff", padding: 24 }}>
        <Text style={{ color: NAVY, fontSize: 18, fontWeight: "800", marginBottom: 8 }}>Something went wrong</Text>
        <Text style={{ color: "#64748b", fontSize: 14, marginBottom: 20 }}>{error}</Text>
        <PrimaryButton label="Go back" onPress={() => router.back()} />
      </SafeAreaView>
    );
  }
  if (!walk) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: "#ffffff", alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator size="large" color={NAVY} />
      </SafeAreaView>
    );
  }

  const n = semNum ?? 0;
  const transferStep = n + 1;
  const gradesStep   = n + 2;
  const reviewStep   = n + 3;
  const totalSteps   = reviewStep;

  function back() {
    if (step === 0) router.back();
    else if (step === reviewStep && !doneEntries.length) setStep(transferStep);
    else setStep(step - 1);
  }
  function next() {
    if (step === transferStep && !doneEntries.length) setStep(reviewStep);
    else setStep(step + 1);
  }

  let body: React.ReactNode;
  let footer: React.ReactNode = <PrimaryButton label="Next" onPress={next} />;

  if (step === 0) {
    footer = null;
    body = (
      <>
        <Heading title="Which semester are you in?" sub={`Count your Fall and Spring semesters at Penn State, including this one (${termLabel(walk.current_term)}).`} />
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
          {Array.from({ length: 10 }, (_, i) => i + 1).map((v) => (
            <TouchableOpacity
              key={v}
              onPress={() => chooseSemester(v)}
              style={{
                width: "30%", paddingVertical: 16, borderRadius: 14, alignItems: "center",
                borderWidth: 1.5, borderColor: semNum === v ? NAVY : "#e2e8f0",
                backgroundColor: semNum === v ? "#f0f4ff" : "#ffffff",
              }}
            >
              <Text style={{ color: NAVY, fontSize: 16, fontWeight: "800" }}>{ORDINAL[v - 1]}</Text>
              <Text style={{ color: "#94a3b8", fontSize: 10, marginTop: 2 }}>{ORDINAL_WORD[v - 1]} semester</Text>
            </TouchableOpacity>
          ))}
        </View>
      </>
    );
  } else if (step >= 1 && step <= n) {
    const k = step - 1;
    const isCurrent = k === n - 1;
    const cardSlots = slots[k] ?? [];
    const card = cards[k];
    body = (
      <>
        <Heading
          title={isCurrent ? `This semester · ${termLabel(terms[k])}` : termLabel(terms[k])}
          sub={cardSlots.length
            ? (isCurrent
                ? "Your plan has these for this semester. Uncheck anything you're not taking, and add anything else."
                : "Your plan has these for this semester. Uncheck anything you didn't take, and add anything else.")
            : (isCurrent ? "Add the classes you're taking this semester." : "Add the classes you took this semester.")}
          badge={`${ORDINAL[k]} semester`}
        />
        {cardSlots.map((sl) => {
          const it = sl.item;
          const moved = sl.movedFrom ? `Moved from ${termLabel(sl.movedFrom)}` : undefined;
          if (it.kind === "course") {
            const on = isChecked(card, sl);
            return (
              <Row key={sl.id} onPress={() => updateCard(k, (c) => ({ ...c, checked: { ...c.checked, [sl.id]: !on } }))}>
                <CourseText code={it.code} title={it.title} caption={moved} dim={!on} />
                <Check on={on} />
              </Row>
            );
          }
          if (it.kind === "choice") {
            const picked = choiceOf(card, sl);
            return (
              <View key={sl.id} style={rowBox}>
                <Text style={{ color: "#94a3b8", fontSize: 11, fontWeight: "700", marginBottom: 8 }}>
                  {moved ? `ONE OF THESE · ${moved.toUpperCase()}` : "ONE OF THESE"}
                </Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                  {[...it.options.map((o) => o.code), null].map((code) => {
                    const sel = picked === code;
                    return (
                      <TouchableOpacity
                        key={code ?? "none"}
                        onPress={() => updateCard(k, (c) => ({ ...c, choice: { ...c.choice, [sl.id]: code } }))}
                        style={{
                          paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
                          backgroundColor: sel ? NAVY : "#f1f5f9",
                        }}
                      >
                        <Text style={{ color: sel ? "#ffffff" : "#475569", fontSize: 13, fontWeight: "700" }}>
                          {code ?? "Neither"}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>
            );
          }
          const picked = card.open[sl.id];
          return picked ? (
            <View key={sl.id} style={[rowBox, { flexDirection: "row", alignItems: "center" }]}>
              <CourseText code={picked.code} title={picked.title} caption={it.label} />
              <TouchableOpacity hitSlop={10} onPress={() => updateCard(k, (c) => ({ ...c, open: { ...c.open, [sl.id]: null } }))}>
                <Text style={{ color: "#e11d48", fontSize: 16, fontWeight: "700" }}>✕</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <TouchableOpacity
              key={sl.id}
              onPress={() => setSearch({ kind: "open", card: k, slot: sl.id })}
              style={[rowBox, { borderStyle: "dashed", borderColor: "#cbd5e1", flexDirection: "row", alignItems: "center" }]}
            >
              <View style={{ flex: 1 }}>
                <Text style={{ color: "#475569", fontSize: 14, fontWeight: "700" }}>{it.label}</Text>
                <Text style={{ color: "#94a3b8", fontSize: 12, marginTop: 2 }}>Tap to choose the class you took, or leave blank</Text>
              </View>
              <Text style={{ color: "#2a5298", fontSize: 18 }}>+</Text>
            </TouchableOpacity>
          );
        })}
        {card.extras.map((c, j) => (
          <View key={`x${c.code}`} style={[rowBox, { flexDirection: "row", alignItems: "center" }]}>
            <CourseText code={c.code} title={c.title} />
            <TouchableOpacity hitSlop={10} onPress={() => updateCard(k, (cd) => ({ ...cd, extras: cd.extras.filter((_, x) => x !== j) }))}>
              <Text style={{ color: "#e11d48", fontSize: 16, fontWeight: "700" }}>✕</Text>
            </TouchableOpacity>
          </View>
        ))}
        {!walk.has_plan && walk.suggestions.some((s) => !takenCodes.has(s.code)) && (
          <>
            <Text style={{ color: "#94a3b8", fontSize: 11, fontWeight: "700", letterSpacing: 0.8, marginTop: 8, marginBottom: 8 }}>
              FROM YOUR MAJOR
            </Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
              {walk.suggestions.filter((s) => !takenCodes.has(s.code)).slice(0, 18).map((s) => (
                <TouchableOpacity
                  key={s.code}
                  onPress={() => updateCard(k, (c) => ({ ...c, extras: [...c.extras, s] }))}
                  style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: "#f0f4ff" }}
                >
                  <Text style={{ color: NAVY, fontSize: 13, fontWeight: "700" }}>+ {s.code}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </>
        )}
        <TouchableOpacity onPress={() => setSearch({ kind: "extra", card: k })} style={{ paddingVertical: 14 }}>
          <Text style={{ color: "#2a5298", fontSize: 14, fontWeight: "700" }}>
            + {isCurrent ? "I'm taking something else" : "I took something else"}
          </Text>
        </TouchableOpacity>
      </>
    );
  } else if (step === transferStep) {
    body = (
      <>
        <Heading
          title="Credit from before Penn State"
          sub="AP exams, dual enrollment, or classes transferred from another college. Skip this if you don't have any."
        />
        {transfer.map((c, j) => (
          <View key={c.code} style={[rowBox, { flexDirection: "row", alignItems: "center" }]}>
            <CourseText code={c.code} title={c.title} />
            <TouchableOpacity hitSlop={10} onPress={() => setTransfer((x) => x.filter((_, i) => i !== j))}>
              <Text style={{ color: "#e11d48", fontSize: 16, fontWeight: "700" }}>✕</Text>
            </TouchableOpacity>
          </View>
        ))}
        <TouchableOpacity onPress={() => setSearch({ kind: "transfer" })} style={{ paddingVertical: 14 }}>
          <Text style={{ color: "#2a5298", fontSize: 14, fontWeight: "700" }}>+ Add the Penn State course it counted as</Text>
        </TouchableOpacity>
      </>
    );
    footer = <PrimaryButton label={transfer.length ? "Next" : "I don't have any"} onPress={next} />;
  } else if (step === gradesStep) {
    body = (
      <>
        <Heading
          title="Did you get a C or better in all of these?"
          sub="Some requirements need a C or better. We don't need your exact grades."
        />
        <View style={{ flexDirection: "row", gap: 10, marginBottom: 16 }}>
          {[true, false].map((v) => (
            <TouchableOpacity
              key={String(v)}
              onPress={() => setAllC(v)}
              style={{
                flex: 1, paddingVertical: 14, borderRadius: 14, alignItems: "center",
                borderWidth: 1.5, borderColor: allC === v ? NAVY : "#e2e8f0",
                backgroundColor: allC === v ? "#f0f4ff" : "#ffffff",
              }}
            >
              <Text style={{ color: NAVY, fontSize: 15, fontWeight: "800" }}>{v ? "Yes" : "No, not all"}</Text>
            </TouchableOpacity>
          ))}
        </View>
        {allC === false && (
          <>
            <Text style={{ color: "#64748b", fontSize: 13, marginBottom: 10 }}>Tap the ones below a C.</Text>
            {doneEntries.map((e) => {
              const low = !!belowC[e.course_code];
              return (
                <Row key={e.course_code} onPress={() => setBelowC((b) => ({ ...b, [e.course_code]: !low }))}>
                  <CourseText code={e.course_code} title={e.title} caption={termLabel(e.term)} />
                  <Text style={{ color: low ? "#e11d48" : "#cbd5e1", fontSize: 12, fontWeight: "800" }}>
                    {low ? "BELOW C" : "C or better"}
                  </Text>
                </Row>
              );
            })}
          </>
        )}
      </>
    );
    footer = <PrimaryButton label="Next" onPress={next} disabled={allC === null} />;
  } else {
    const groups: { label: string; step: number; list: typeof entries }[] = [];
    const xfer = entries.filter((e) => e.status === "transfer");
    if (xfer.length) groups.push({ label: "Transfer / AP credit", step: transferStep, list: xfer });
    terms.forEach((t, k) => {
      groups.push({
        label: `${termLabel(t)}${k === n - 1 ? " · in progress" : ""}`,
        step: k + 1,
        list: entries.filter((e) => e.term === t && e.status !== "transfer"),
      });
    });
    const credits = entries.filter((e) => e.status !== "in_progress").reduce((s, e) => s + (e.credits ?? 0), 0);
    body = (
      <>
        <Heading
          title="Review your classes"
          sub={`${entries.length} classes · ${credits} credits completed. Tap a semester to change it.`}
        />
        {groups.map((g) => (
          <TouchableOpacity key={g.label} onPress={() => setStep(g.step)} activeOpacity={0.8} style={[rowBox, { paddingVertical: 12 }]}>
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: g.list.length ? 6 : 0 }}>
              <Text style={{ flex: 1, color: "#94a3b8", fontSize: 11, fontWeight: "700", letterSpacing: 0.8 }}>
                {g.label.toUpperCase()}
              </Text>
              <Text style={{ color: "#2a5298", fontSize: 12, fontWeight: "700" }}>Edit</Text>
            </View>
            {g.list.length ? (
              <Text style={{ color: NAVY, fontSize: 13, lineHeight: 20 }}>
                {g.list.map((e) => (allC === false && belowC[e.course_code] ? `${e.course_code} (below C)` : e.course_code)).join(" · ")}
              </Text>
            ) : (
              <Text style={{ color: "#cbd5e1", fontSize: 13 }}>No classes</Text>
            )}
          </TouchableOpacity>
        ))}
        <TouchableOpacity onPress={() => setStep(0)} style={{ paddingVertical: 10 }}>
          <Text style={{ color: "#64748b", fontSize: 13, fontWeight: "600" }}>
            Wrong semester count? You said this is your {ORDINAL[n - 1]} semester. Change it
          </Text>
        </TouchableOpacity>
        <Text style={{ color: "#94a3b8", fontSize: 12, lineHeight: 17, marginTop: 8 }}>
          GradGPS treats these as self-reported. You can upload your transcript any time to replace them.
        </Text>
      </>
    );
    footer = <PrimaryButton label={saving ? "" : "Save my classes"} onPress={save} loading={saving} />;
  }

  const searchItem = search?.kind === "open"
    ? (slots[search.card]?.find((sl) => sl.id === search.slot)?.item as Extract<WalkItem, { kind: "open" }> | undefined) ?? null
    : null;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: "#ffffff" }} edges={["top", "left", "right", "bottom"]}>
      <View style={{ paddingHorizontal: 20, paddingTop: 8, paddingBottom: 6, flexDirection: "row", alignItems: "center" }}>
        <TouchableOpacity onPress={back} hitSlop={10}>
          <Text style={{ color: NAVY, fontSize: 15, fontWeight: "700" }}>‹ Back</Text>
        </TouchableOpacity>
        <View style={{ flex: 1 }} />
        {step > 0 && (
          <Text style={{ color: "#94a3b8", fontSize: 12, fontWeight: "600" }}>Step {step} of {totalSteps}</Text>
        )}
      </View>
      {step > 0 && (
        <View style={{ height: 3, backgroundColor: "#f1f5f9", marginHorizontal: 20, borderRadius: 2 }}>
          <View style={{ height: 3, backgroundColor: NAVY, borderRadius: 2, width: `${Math.round((step / totalSteps) * 100)}%` }} />
        </View>
      )}
      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 32 }} keyboardShouldPersistTaps="handled">
        {body}
      </ScrollView>
      {footer && <View style={{ paddingHorizontal: 20, paddingBottom: 12, paddingTop: 8 }}>{footer}</View>}

      <CourseSearchModal
        visible={search !== null}
        title={searchItem ? searchItem.label : search?.kind === "transfer" ? "Add transfer / AP credit" : "Add a class"}
        genEd={searchItem?.gen_ed}
        dept={searchItem?.dept}
        suggested={searchItem?.suggested}
        exclude={takenCodes}
        onPick={onPick}
        onClose={() => setSearch(null)}
      />
    </SafeAreaView>
  );
}

// ── Small pieces ─────────────────────────────────────────────────────────────

const rowBox = {
  borderWidth: 1, borderColor: "#eef2f7", borderRadius: 14,
  paddingHorizontal: 14, paddingVertical: 12, marginBottom: 10, backgroundColor: "#ffffff",
} as const;

function Heading({ title, sub, badge }: { title: string; sub: string; badge?: string }) {
  return (
    <View style={{ marginBottom: 18 }}>
      {badge && (
        <Text style={{ color: "#94a3b8", fontSize: 11, fontWeight: "700", letterSpacing: 0.9, marginBottom: 6 }}>
          {badge.toUpperCase()}
        </Text>
      )}
      <Text style={{ color: "#0f172a", fontSize: 24, fontWeight: "800", marginBottom: 6 }}>{title}</Text>
      <Text style={{ color: "#64748b", fontSize: 14, lineHeight: 20 }}>{sub}</Text>
    </View>
  );
}

function Row({ children, onPress }: { children: React.ReactNode; onPress: () => void }) {
  return (
    <TouchableOpacity onPress={onPress} activeOpacity={0.7} style={[rowBox, { flexDirection: "row", alignItems: "center" }]}>
      {children}
    </TouchableOpacity>
  );
}

function CourseText({ code, title, caption, dim }: { code: string; title?: string; caption?: string; dim?: boolean }) {
  return (
    <View style={{ flex: 1, marginRight: 10, opacity: dim ? 0.4 : 1 }}>
      {!!caption && <Text style={{ color: "#94a3b8", fontSize: 11, marginBottom: 2 }}>{caption}</Text>}
      <Text style={{ color: NAVY, fontSize: 14, fontWeight: "700", textDecorationLine: dim ? "line-through" : "none" }}>{code}</Text>
      {!!title && <Text style={{ color: "#64748b", fontSize: 12, marginTop: 2 }} numberOfLines={1}>{title}</Text>}
    </View>
  );
}

function Check({ on }: { on: boolean }) {
  return (
    <View style={{
      width: 24, height: 24, borderRadius: 7, alignItems: "center", justifyContent: "center",
      borderWidth: 1.5, borderColor: on ? NAVY : "#cbd5e1", backgroundColor: on ? NAVY : "#ffffff",
    }}>
      {on && <Text style={{ color: "#ffffff", fontSize: 14, fontWeight: "800" }}>✓</Text>}
    </View>
  );
}

function PrimaryButton({ label, onPress, disabled, loading }: {
  label: string; onPress: () => void; disabled?: boolean; loading?: boolean;
}) {
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled || loading}
      activeOpacity={0.85}
      style={{
        backgroundColor: disabled ? "#cbd5e1" : NAVY, borderRadius: 16,
        paddingVertical: 16, alignItems: "center",
      }}
    >
      {loading
        ? <ActivityIndicator color="#ffffff" />
        : <Text style={{ color: "#ffffff", fontSize: 16, fontWeight: "700" }}>{label}</Text>}
    </TouchableOpacity>
  );
}
