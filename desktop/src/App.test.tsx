import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";
import type { View, VoiceClient } from "./client";

function fixture() {
  let view: View = { connection: "connected", error: "", note: "", preparing: false,
    snapshot: { kind: "snapshot", version: 1, sequence: 0, state: "idle", busy: false,
      microphone_enabled: true, turn_id: null, ready: true, device: null, output_device: null, outputs: [], preparing_speech: false, draft: "", devices: [], messages: [] } };
  let notify = () => {};
  const client = { getSnapshot: () => view, subscribe: (fn: () => void) => { notify = fn; return () => {}; },
    press: vi.fn(), release: vi.fn(), suspend: vi.fn(), disconnect: vi.fn(), prepare: vi.fn(),
    microphone: vi.fn(), selectDevice: vi.fn(), selectOutput: vi.fn(), reset: vi.fn(), connect: vi.fn() };
  render(<App client={client as unknown as VoiceClient} />);
  return { client, change: (next: Partial<View>) => act(() => { view = { ...view, ...next }; notify(); }) };
}
afterEach(cleanup);
test("keyboard hold ignores auto-repeat and releases on key up", () => {
  const { client } = fixture(); const button = screen.getByRole("button", { name: /Hold to talk/ });
  fireEvent.keyDown(button, { key: " " }); fireEvent.keyDown(button, { key: " ", repeat: true });
  expect(client.press).toHaveBeenCalledTimes(1);
  fireEvent.keyUp(button, { key: " " }); expect(client.release).toHaveBeenCalledTimes(1);
});
test.each(["blur", "escape", "hidden", "pointercancel"])("%s turns the microphone off", reason => {
  const { client } = fixture(); const button = screen.getByRole("button", { name: /Hold to talk/ });
  fireEvent.keyDown(button, { key: "Enter" });
  if (reason === "blur") fireEvent.blur(window);
  if (reason === "escape") fireEvent.keyDown(window, { key: "Escape" });
  if (reason === "hidden") {
    const spy = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange")); spy.mockRestore();
  }
  if (reason === "pointercancel") fireEvent.pointerCancel(button);
  expect(client.suspend).toHaveBeenCalled();
  expect(screen.getByRole("button", { name: /Hold to talk/ })).toBeTruthy();
});
test("disconnect clears the held button and disables it", () => {
  const { change } = fixture(); fireEvent.keyDown(screen.getByRole("button", { name: /Hold to talk/ }), { key: " " });
  change({ connection: "disconnected", snapshot: null });
  expect((screen.getByRole("button", { name: /Hold to talk/ }) as HTMLButtonElement).disabled).toBe(true);
});
test("pointer hold releases normally and lost capture cancels", () => {
  const { client } = fixture(); const button = screen.getByRole("button", { name: /Hold to talk/ });
  fireEvent(button, new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
  expect(client.press).toHaveBeenCalledTimes(1);
  fireEvent.pointerUp(button); expect(client.release).toHaveBeenCalledTimes(1);
  fireEvent(button, new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
  fireEvent.lostPointerCapture(button); expect(client.suspend).toHaveBeenCalledTimes(1);
});
test("streams escaped draft text and replaces it with the completed answer", () => {
  const { client, change } = fixture();
  const initial = client.getSnapshot().snapshot!;
  change({ snapshot: { ...initial, state: "thinking", busy: true, draft: "<img src=x onerror=alert(1)>" } });
  expect(screen.getByLabelText("Reply in progress").textContent).toContain("<img src=x");
  expect(document.querySelector(".messages img")).toBeNull();
  expect(screen.getByText("Thinking about your question")).toBeTruthy();
  change({ snapshot: { ...initial, draft: "", messages: [{ role: "assistant", content: "Final answer" }] } });
  expect(screen.queryByLabelText("Reply in progress")).toBeNull();
  expect(screen.getByText("Final answer")).toBeTruthy();
});
test("stop response disables microphone and cancellation removes the draft", () => {
  const { client, change } = fixture();
  const initial = client.getSnapshot().snapshot!;
  change({ snapshot: { ...initial, state: "thinking", busy: true, draft: "Partial answer" } });
  fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
  expect(client.suspend).toHaveBeenCalledOnce();
  change({ snapshot: { ...initial, draft: "", microphone_enabled: false } });
  expect(screen.queryByText("Partial answer")).toBeNull();
});
test("preparing speech and speaking retain the completed answer and expose stop", () => {
  const { client, change } = fixture(); const initial = client.getSnapshot().snapshot!;
  const messages = [{ role: "assistant" as const, content: "A completed answer" }];
  change({ snapshot: { ...initial, state: "thinking", busy: true, preparing_speech: true, messages } });
  expect(screen.getByText("Preparing speech")).toBeTruthy();
  expect(screen.getByText("A completed answer")).toBeTruthy();
  expect((screen.getByRole("button", { name: /Hold to talk/ }) as HTMLButtonElement).disabled).toBe(true);
  change({ snapshot: { ...initial, state: "speaking", busy: true, messages } });
  expect(screen.getByText("Speaking to you")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Stop speaking" }));
  expect(client.suspend).toHaveBeenCalledOnce();
  change({ snapshot: { ...initial, microphone_enabled: false, messages } });
  expect(screen.getByText("A completed answer")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Stop speaking" })).toBeNull();
});
test("output selection is restricted to microphone-off idle sessions", () => {
  const { client, change } = fixture(); const initial = client.getSnapshot().snapshot!;
  const select = screen.getByLabelText("Speaker output") as HTMLSelectElement;
  expect(select.disabled).toBe(true);
  change({ snapshot: { ...initial, microphone_enabled: false,
    outputs: [{ index: 4, name: "Synthetic speaker", sample_rate: 48000 }] } });
  expect(select.disabled).toBe(false);
  fireEvent.change(select, { target: { value: "4" } });
  expect(client.selectOutput).toHaveBeenLastCalledWith(4);
  fireEvent.change(select, { target: { value: "default" } });
  expect(client.selectOutput).toHaveBeenLastCalledWith(null);
  change({ snapshot: { ...initial, microphone_enabled: false, busy: true } });
  expect(select.disabled).toBe(true);
});
