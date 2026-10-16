import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { VoiceClient } from "./client";
import { parsePacket, type Snapshot } from "./protocol";

export const snapshot: Snapshot = {
  kind: "snapshot", version: 1, sequence: 0, state: "idle", busy: false,
  microphone_enabled: true, turn_id: null, ready: true, device: null, devices: [], messages: [],
};
class FakeSocket {
  static OPEN = 1;
  static latest: FakeSocket;
  readyState = 1;
  sent: Record<string, unknown>[] = [];
  onopen = () => {};
  onmessage = (_: { data: string }) => {};
  onerror = () => {};
  onclose = (_: { code: number }) => {};
  constructor(readonly url: string) { FakeSocket.latest = this; }
  send(raw: string) { this.sent.push(JSON.parse(raw)); }
  close() { this.readyState = 3; }
  packet(packet: unknown) { this.onmessage({ data: JSON.stringify(packet) }); }
  ack(index: number, turn: string | null = null) {
    this.packet({ kind: "ack", id: this.sent[index].id, turn_id: turn, error: null });
  }
}
let client: VoiceClient;
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("WebSocket", FakeSocket); client = new VoiceClient(); });
afterEach(() => { client.disconnect(); vi.useRealTimers(); vi.unstubAllGlobals(); });
function connect() {
  client.connect("a".repeat(43));
  const socket = FakeSocket.latest; socket.onopen(); socket.packet(snapshot); return socket;
}
test("authenticates in a frame and keeps credentials out of URL, view and storage", () => {
  const socket = connect();
  expect(socket.url).toBe("ws://127.0.0.1:8765/session");
  expect(socket.sent[0]).toEqual({ version: 1, token: "a".repeat(43) });
  expect(JSON.stringify(client.getSnapshot())).not.toContain("a".repeat(43));
  expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
});
test("a quick release waits for the start acknowledgement and releases the correct turn", async () => {
  const socket = connect();
  const pressing = client.press(); client.release();
  expect(socket.sent.map(p => p.action)).toEqual([undefined, "start"]);
  socket.ack(1, "test-turn"); await pressing;
  expect(socket.sent[2]).toMatchObject({ action: "release", turn_id: "test-turn" }); socket.ack(2);
});
test("duplicate presses cannot start overlapping turns", async () => {
  const socket = connect(); const pressing = client.press(); await client.press();
  expect(socket.sent.length).toBe(2); socket.ack(1, "turn"); await pressing;
});
test("focus loss disables the microphone even while the start is pending", async () => {
  const socket = connect(); const pressing = client.press(); client.suspend();
  expect(socket.sent[2]).toMatchObject({ action: "microphone", enabled: false });
  socket.ack(1, "turn"); socket.ack(2); await pressing;
  expect(socket.sent[3]).toMatchObject({ action: "release", turn_id: "turn" }); socket.ack(3);
});
test("a silent backend expires the connection and clears microphone controls", async () => {
  const socket = connect(); await vi.advanceTimersByTimeAsync(10001);
  expect(socket.readyState).toBe(3); expect(client.getSnapshot().snapshot).toBeNull();
  expect(client.getSnapshot().connection).toBe("disconnected");
});
test("a socket which never opens times out", async () => {
  client.connect("a".repeat(43)); await vi.advanceTimersByTimeAsync(8001);
  expect(client.getSnapshot().connection).toBe("disconnected");
});
test("stale sockets and older snapshots cannot overwrite current state", () => {
  const old = connect(); const current = connect();
  current.packet({ ...snapshot, sequence: 4, microphone_enabled: false });
  current.packet({ ...snapshot, sequence: 3 }); old.packet({ ...snapshot, sequence: 8 });
  expect(client.getSnapshot().snapshot?.sequence).toBe(4);
  expect(client.getSnapshot().snapshot?.microphone_enabled).toBe(false);
});
test.each([null, { ...snapshot, version: 2 }, { ...snapshot, microphone_enabled: "yes" },
  { ...snapshot, messages: [{ role: "user", content: "x".repeat(8193) }] }])("rejects malformed responses: %j", packet => {
  expect(() => parsePacket(JSON.stringify(packet))).toThrow();
  const socket = connect(); socket.packet(packet); expect(socket.readyState).toBe(3);
});
test("microphone off prevents starting a turn", async () => {
  const socket = connect(); socket.packet({ ...snapshot, microphone_enabled: false }); await client.press();
  expect(socket.sent.length).toBe(1);
});
