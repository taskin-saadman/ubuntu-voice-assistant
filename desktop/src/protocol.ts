export const states = ["idle", "listening", "transcribing", "thinking", "acting", "speaking", "error"] as const;
export type AssistantState = typeof states[number];
export interface Snapshot {
  kind: "snapshot"; version: 1; sequence: number; state: AssistantState;
  busy: boolean; microphone_enabled: boolean; turn_id: string | null;
  ready: boolean; device: number | null;
  devices: { index: number; name: string; sample_rate: number }[];
  messages: { role: "user" | "assistant"; content: string }[];
}
export interface Ack { kind: "ack"; id: string; turn_id: string | null; error: string | null }
export interface EventPacket {
  kind: "event"; event: {
    sequence: number; kind: string; failure: { message: string } | null; outcome: string | null;
  };
}
export type Packet = Snapshot | Ack | EventPacket;
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, size: number): value is string => typeof value === "string" && value.length <= size;
const nullableText = (value: unknown, size: number) => value === null || text(value, size);
const nullableIndex = (value: unknown) => value === null || (Number.isInteger(value) && Number(value) >= 0);

export function parsePacket(raw: string): Packet {
  if (raw.length > 1_000_000) throw new Error("Oversized response");
  const p: unknown = JSON.parse(raw);
  if (!object(p)) throw new Error("Invalid response");
  if (p.kind === "ack" && text(p.id, 36) && nullableText(p.turn_id, 36) && nullableText(p.error, 300))
    return p as unknown as Ack;
  if (p.kind === "event" && object(p.event) && Number.isInteger(p.event.sequence)
    && text(p.event.kind, 20) && nullableText(p.event.outcome, 20)
    && (p.event.failure === null || (object(p.event.failure) && text(p.event.failure.message, 300))))
    return p as unknown as EventPacket;
  if (p.kind === "snapshot" && p.version === 1 && Number.isInteger(p.sequence)
    && states.includes(p.state as AssistantState) && typeof p.busy === "boolean"
    && typeof p.microphone_enabled === "boolean" && typeof p.ready === "boolean"
    && nullableText(p.turn_id, 36) && nullableIndex(p.device)
    && Array.isArray(p.devices) && p.devices.length <= 128
    && p.devices.every(d => object(d) && Number.isInteger(d.index) && Number(d.index) >= 0
      && text(d.name, 256) && typeof d.sample_rate === "number")
    && Array.isArray(p.messages) && p.messages.length <= 20
    && p.messages.every(m => object(m) && (m.role === "user" || m.role === "assistant") && text(m.content, 8192)))
    return p as unknown as Snapshot;
  throw new Error("Invalid response");
}
