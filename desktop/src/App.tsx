import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { VoiceClient } from "./client";

export function App({ client }: { client: VoiceClient }) {
  const view = useSyncExternalStore(client.subscribe, client.getSnapshot);
  const [key, setKey] = useState("");
  const [held, setHeld] = useState(false);
  const heldRef = useRef(false);
  const snapshot = view.snapshot;
  const connected = view.connection === "connected";
  const enabled = snapshot?.microphone_enabled ?? false;
  const state = snapshot?.state ?? "idle";
  useEffect(() => {
    if (!connected || !enabled || state === "error" || state === "transcribing") {
      heldRef.current = false; setHeld(false);
    }
  }, [connected, enabled, state]);
  const press = () => { heldRef.current = true; setHeld(true); void client.press(); };
  const release = () => { heldRef.current = false; setHeld(false); client.release(); };
  const cancel = () => { heldRef.current = false; setHeld(false); client.suspend(); };
  useEffect(() => {
    const suspend = () => { heldRef.current = false; setHeld(false); client.suspend(); };
    const visibility = () => { if (document.hidden) suspend(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") suspend(); };
    window.addEventListener("blur", suspend);
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("blur", suspend);
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("keydown", escape);
      client.disconnect();
    };
  }, [client]);
  const canTalk = connected && snapshot?.ready && enabled && state === "idle" && !snapshot.busy;
  const label = !connected ? "Connect to begin" : view.preparing ? "Loading speech model"
    : !snapshot?.ready ? "Speech model not loaded" : !enabled ? "Microphone disabled"
    : state === "idle" ? "Ready when you are" : state === "listening" ? "Listening to you"
    : state === "transcribing" ? "Turning speech into text" : state === "error" ? "Let’s try again" : state;

  return <main className="app">
    <header><div className="brand"><span className="brand-dot" />LOCAL VOICE</div>
      <span className="privacy">{connected ? "● Local connection" : "○ Disconnected"}</span></header>
    <section className="workspace">
      <section className="assistant glass" aria-label="Voice controls">
        <div className="eyebrow">YOUR PRIVATE SPACE</div>
        <h1>A thought.<br /><span>A conversation.</span></h1>
        <div className={`orb-stage ${state}`} aria-hidden="true"><div className="orb-halo" /><div className="orb" /><div className="orb-ring" /></div>
        <p className="state" role="status">{label}</p>
        <p className="hint">{state === "listening" ? "Release to transcribe." : "Your voice stays on this laptop."}</p>
        <button className={`talk ${held ? "held" : ""}`} disabled={!canTalk && !held}
          onPointerDown={event => {
            if (event.button !== 0 || !canTalk) return;
            event.preventDefault(); event.currentTarget.setPointerCapture?.(event.pointerId); press();
          }}
          onPointerUp={release} onPointerCancel={cancel}
          onLostPointerCapture={() => { if (heldRef.current) cancel(); }}
          onBlur={() => { if (heldRef.current) cancel(); }}
          onKeyDown={event => {
            if ((event.key === " " || event.key === "Enter") && !event.repeat && canTalk) { event.preventDefault(); press(); }
          }}
          onKeyUp={event => { if (event.key === " " || event.key === "Enter") { event.preventDefault(); release(); } }}>
          <span aria-hidden="true">◉</span> {held ? "Release to transcribe" : "Hold to talk"}
        </button>
        <span className="keyboard-hint">Hold Space or Enter when focused · Esc turns the microphone off</span>
        <button className={`mic-toggle ${enabled ? "enabled" : ""}`} role="switch" aria-checked={enabled}
          disabled={!connected || (!enabled && (!snapshot?.ready || view.preparing || snapshot.busy))}
          onClick={() => { if (enabled) cancel(); else void client.microphone(true); }}>
          <span className="toggle-track" aria-hidden="true"><i /></span>
          {enabled ? "Microphone enabled" : "Microphone disabled"}
        </button>
      </section>
      <aside className="side">
        <section className="connection glass" aria-label="Connection and microphone settings">
          <div className="section-title"><h2>Session</h2><span className="tag">ON DEVICE</span></div>
          {!connected ? <form onSubmit={event => { event.preventDefault(); client.connect(key.trim()); setKey(""); }}>
            <label htmlFor="connection-key">Connection key</label>
            <input id="connection-key" type="password" autoComplete="off" spellCheck={false} value={key}
              onChange={event => setKey(event.target.value)} placeholder="Paste the key from your backend" maxLength={128} />
            <button className="secondary" disabled={!key || view.connection === "connecting"}>
              {view.connection === "connecting" ? "Connecting…" : "Connect locally"}</button>
            <p className="small">The key is kept only for this connection.</p>
          </form> : <>
            <div className="session-actions"><button className="secondary" disabled={view.preparing || enabled || snapshot?.busy}
              onClick={() => void client.prepare()}>{view.preparing ? "Loading…" : snapshot?.ready ? "Refresh devices" : "Load speech model"}</button>
              <button className="quiet" onClick={client.disconnect}>Disconnect</button></div>
            <label htmlFor="input-device">Microphone input</label>
            <select id="input-device" value={snapshot?.device ?? "default"} disabled={!snapshot?.ready || enabled || snapshot.busy}
              onChange={event => void client.selectDevice(event.target.value === "default" ? null : Number(event.target.value))}>
              <option value="default">System default input</option>
              {snapshot?.devices.map(device => <option value={device.index} key={device.index}>{device.name}</option>)}
            </select>
            <p className="small">Disable the microphone to change inputs. Switching away from this window also disables it.</p>
          </>}
        </section>
        <section className="conversation glass" aria-label="Conversation">
          <div className="section-title"><h2>Conversation</h2><span className="muted">This session only</span></div>
          <div className="messages" aria-live="polite" aria-relevant="additions text">
            {!snapshot?.messages.length ? <div className="empty"><span aria-hidden="true">〰</span><h3>Start with your voice</h3><p>Your words will appear here.<br />Speech recognition runs locally.</p></div>
              : snapshot.messages.map((message, index) => <article className="message" key={index}>
                <span className="speaker">{message.role === "user" ? "YOU" : "ASSISTANT"}</span><p>{message.content}</p></article>)}
          </div>
          <p className="small milestone">Transcription preview · Replies and speech playback come next.</p>
        </section>
      </aside>
    </section>
    {(view.error || view.note) && <div className="notice glass" role={view.error ? "alert" : "status"}>
      <span>{view.error || view.note}</span>
      {connected && state === "error" && <button className="quiet" disabled={snapshot?.busy} onClick={() => void client.reset()}>Reset assistant</button>}
    </div>}
    <footer><span>CPU speech recognition · Local storage in memory</span><span>No cloud connection</span></footer>
  </main>;
}
