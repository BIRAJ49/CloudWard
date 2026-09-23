import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useControlPlaneEvents, type ControlPlaneEvent } from "../hooks/use-control-plane-events";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly listeners = new Map<string, Array<(event: Event) => void>>();
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;

  constructor(readonly url: string, readonly options?: EventSourceInit) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, listener: EventListenerOrEventListenerObject) {
    const callback = typeof listener === "function" ? listener : listener.handleEvent.bind(listener);
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), callback]);
  }

  close() { this.closed = true; }

  emit(name: string, data: Record<string, unknown>, id: string) {
    const event = new MessageEvent(name, { data: JSON.stringify(data), lastEventId: id });
    if (name === "message") this.onmessage?.(event);
    for (const listener of this.listeners.get(name) ?? []) listener(event);
  }
}

function Harness({ onEvent }: { onEvent: (event: ControlPlaneEvent) => void }) {
  useControlPlaneEvents(onEvent);
  return null;
}

describe("authenticated SSE reconnect", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    FakeEventSource.instances = [];
    window.sessionStorage.clear();
  });

  it("reconnects with the last durable event ID", () => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeEventSource);
    const received = vi.fn();
    render(<Harness onEvent={received} />);

    const first = FakeEventSource.instances[0];
    expect(first.options).toEqual({ withCredentials: true });
    act(() => first.emit("incident.created", { type: "incident.created", incident_id: "inc-1" }, "42"));
    expect(received).toHaveBeenCalledWith(expect.objectContaining({ incident_id: "inc-1" }));

    act(() => {
      first.onerror?.(new Event("error"));
      vi.advanceTimersByTime(1_000);
    });

    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances[1].url).toContain("last_event_id=42");
  });

  it("ignores duplicate and malformed frames without poisoning the cursor", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const received = vi.fn();
    render(<Harness onEvent={received} />);
    const source = FakeEventSource.instances[0];
    act(() => {
      source.emit("message", { incident_id: "first" }, "10");
      source.emit("message", { incident_id: "duplicate" }, "10");
      source.emit("message", { incident_id: "stale" }, "9");
      source.onmessage?.(new MessageEvent("message", { data: "not json", lastEventId: "999" }));
      source.onmessage?.(new MessageEvent("message", { data: "null", lastEventId: "999" }));
      source.emit("message", { incident_id: "next" }, "11");
    });
    expect(received).toHaveBeenCalledTimes(2);
    expect(received).toHaveBeenLastCalledWith({ incident_id: "next" });
    expect(window.sessionStorage.getItem("cloudward.control-plane.last-event-id")).toBe("11");
  });

  it("dispatches cluster observations and incident evidence events", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const received = vi.fn();
    render(<Harness onEvent={received} />);
    const source = FakeEventSource.instances[0];
    act(() => {
      source.emit("cluster.observation", { type: "cluster.observation", cluster_id: "cluster-1" }, "20");
      source.emit("incident.evidence_added", { type: "incident.evidence_added", incident_id: "incident-1" }, "21");
    });
    expect(received).toHaveBeenCalledTimes(2);
    expect(received).toHaveBeenLastCalledWith(expect.objectContaining({ incident_id: "incident-1" }));
  });
});
