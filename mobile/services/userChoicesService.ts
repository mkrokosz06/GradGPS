import api from "./api";
import { SlotKind } from "./timelineService";

export type ChoicePayload = {
  slot_key:       string;
  slot_kind:      SlotKind;
  chosen_course?: string;
  pinned_term?:   string;
};

/** Upsert a class-selector decision (which course fills a slot, and/or the term
 *  it's pinned to). The timeline reads these on its next fetch. */
export async function putChoice(userId: string, payload: ChoicePayload): Promise<void> {
  await api.put("/user-choices", payload, { headers: { "x-user-id": userId } });
}

/** Clear a decision — "let GradGPS choose" again. */
export async function deleteChoice(userId: string, slotKey: string): Promise<void> {
  await api.delete("/user-choices", {
    params: { slot_key: slotKey },
    headers: { "x-user-id": userId },
  });
}
