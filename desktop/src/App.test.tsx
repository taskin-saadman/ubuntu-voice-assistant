import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";
import type { View, VoiceClient } from "./client";

function fixture() {
  let view: View = { connection: "connected", error: "", note: "", preparing: false,
    snapshot: { kind: "snapshot", version: 1, sequence: 0, state: "idle", busy: false,
      microphone_enabled: true, turn_id: null, ready: true, device: null, devices: [], messages: [] } };
  let notify = () => {};
  const client = { getSnapshot: () => view, subscribe: (fn: () => void) => { notify = fn; return () => {}; },
    press: vi.fn(), release: vi.fn(), suspend: vi.fn(), disconnect: vi.fn(), prepare: vi.fn(),
    microphone: vi.fn(), selectDevice: vi.fn(), reset: vi.fn(), connect: vi.fn() };
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
