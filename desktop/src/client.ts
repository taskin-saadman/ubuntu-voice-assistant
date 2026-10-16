import { parsePacket } from "./protocol";
import type { Ack, Snapshot } from "./protocol";

export interface View {
  connection: "disconnected" | "connecting" | "connected";
  snapshot: Snapshot | null; error: string; note: string; preparing: boolean;
}
type Pending = { resolve: (ack: Ack) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> };

export class VoiceClient {
  private socket: WebSocket | null = null;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private connectTimer: ReturnType<typeof setTimeout> | null = null;
  private lastResponse = 0;
  private pending = new Map<string, Pending>();
  private listeners = new Set<() => void>();
  private view: View = { connection: "disconnected", snapshot: null, error: "", note: "", preparing: false };
  private holding = false;
  private starting = false;
  private turn: string | null = null;
  getSnapshot = (): View => this.view;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(changes: Partial<View>) {
    this.view = { ...this.view, ...changes };
    this.listeners.forEach(fn => fn());
  }
  connect(token: string) {
    this.disconnect();
    if (!/^[A-Za-z0-9_-]{43}$/.test(token)) { this.update({ error: "Enter the connection key shown by the backend." }); return; }
    this.update({ connection: "connecting", error: "", note: "" });
    const socket = new WebSocket("ws://127.0.0.1:8765/session");
    this.socket = socket;
    this.connectTimer = setTimeout(() => this.fail("Connection timed out. Check the local backend."), 8000);
    socket.onopen = () => {
      if (this.socket !== socket) return;
      socket.send(JSON.stringify({ version: 1, token }));
      token = "";
      this.lastResponse = Date.now();
      this.heartbeat = setInterval(() => {
        if (Date.now() - this.lastResponse > 8000) { this.fail("Connection lost. Microphone controls disabled."); return; }
        if (this.view.connection === "connected") void this.send("ping").catch(() => {});
      }, 2000);
    };
    socket.onmessage = message => {
      if (this.socket !== socket) return;
      try {
        if (typeof message.data !== "string") throw new Error("Invalid response");
        const packet = parsePacket(message.data);
        this.lastResponse = Date.now();
        if (packet.kind === "snapshot") {
          if (this.connectTimer) clearTimeout(this.connectTimer);
          this.connectTimer = null;
          if (this.view.snapshot && packet.sequence < this.view.snapshot.sequence) return;
          // Snapshots are authoritative, including after journal gaps and reconnects.
          this.update({ connection: "connected", snapshot: packet });
        } else if (packet.kind === "ack") {
          const pending = this.pending.get(packet.id);
          if (pending) {
            clearTimeout(pending.timer); this.pending.delete(packet.id);
            if (packet.error) pending.reject(new Error(packet.error)); else pending.resolve(packet);
          }
        } else {
          if (packet.event.failure) this.update({ error: packet.event.failure.message });
          if (packet.event.outcome === "no_speech") this.update({ note: "No speech detected. Try again when you’re ready." });
        }
      } catch { this.fail("Invalid backend response. Reconnect to continue."); }
    };
    socket.onerror = () => { if (this.socket === socket) this.fail("Cannot reach the local backend."); };
    socket.onclose = event => {
      if (this.socket !== socket) return;
      this.fail(event.code === 4409 ? "Another window owns this session. Close it first."
        : event.code === 4401 || event.code === 4400 ? "Connection rejected. Check the current key."
        : "Disconnected. Microphone controls disabled.");
    };
  }
  disconnect = () => {
    const socket = this.socket;
    this.socket = null;
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = null;
    if (this.connectTimer) clearTimeout(this.connectTimer);
    this.connectTimer = null;
    this.holding = false; this.turn = null;
    this.pending.forEach(p => { clearTimeout(p.timer); p.reject(new Error("Disconnected")); });
    this.pending.clear();
    if (socket) socket.close();
    this.update({ connection: "disconnected", snapshot: null, preparing: false });
  };
  private fail(message: string) { this.disconnect(); this.update({ error: message }); }
  private send(action: string, args: Record<string, unknown> = {}): Promise<Ack> {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return Promise.reject(new Error("Not connected"));
    const id = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.fail("Backend control timed out. Reconnect to continue."); }, 40000);
      this.pending.set(id, { resolve, reject, timer });
      try { this.socket!.send(JSON.stringify({ id, action, ...args })); }
      catch { this.fail("Could not send control. Reconnect to continue."); }
    });
  }
  private report = (error: unknown) => this.update({ error: error instanceof Error ? error.message : "Control failed." });
  async prepare() {
    if (this.view.preparing) return;
    this.update({ preparing: true, error: "", note: "" });
    try { await this.send("prepare"); } catch (error) { this.report(error); }
    finally { this.update({ preparing: false }); }
  }
  async microphone(enabled: boolean) {
    if (!enabled) this.holding = false;
    try { await this.send("microphone", { enabled }); } catch (error) { this.report(error); }
  }
  async selectDevice(device: number | null) {
    try { await this.send("device", { device }); } catch (error) { this.report(error); }
  }
  async reset() {
    this.update({ error: "", note: "" });
    try { await this.send("reset"); } catch (error) { this.report(error); }
  }
  async press() {
    const state = this.view.snapshot;
    if (this.starting || this.holding || !state?.ready || !state.microphone_enabled || state.busy || state.state !== "idle") return;
    this.starting = this.holding = true;
    this.update({ error: "", note: "" });
    try {
      const result = await this.send("start");
      if (result.turn_id) {
        this.turn = result.turn_id;
        if (!this.holding) this.release();
      }
    } catch (error) { this.holding = false; this.report(error); }
    finally { this.starting = false; }
  }
  release = () => {
    this.holding = false;
    const turn = this.turn; this.turn = null;
    if (turn) void this.send("release", { turn_id: turn }).catch(this.report);
  };
  suspend = () => {
    this.holding = false; this.turn = null;
    if (this.view.connection === "connected") void this.microphone(false);
  };
}
