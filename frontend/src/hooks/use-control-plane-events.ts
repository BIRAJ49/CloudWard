import { useEffect, useRef } from "react";
import { API_BASE_URL } from "../lib/api";

export interface ControlPlaneEvent {
  type?: string;
  event_type?: string;
  incident_id?: string;
  security_event_id?: string;
  execution_id?: string;
  [key: string]: unknown;
}

const CURSOR_KEY = "cloudward.control-plane.last-event-id";

function storedCursor(): number {
  try {
    const value = Number(window.sessionStorage.getItem(CURSOR_KEY));
    return Number.isSafeInteger(value) && value > 0 ? value : 0;
  } catch {
    return 0;
  }
}

export function useControlPlaneEvents(
  onEvent: (event: ControlPlaneEvent) => void,
  enabled = true,
) {
  const callback = useRef(onEvent);

  useEffect(() => {
    callback.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;

    let source: EventSource | undefined;
    let reconnectTimer: number | undefined;
    let reconnectAttempt = 0;
    let lastEventId = storedCursor();
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      const cursor = lastEventId > 0 ? `?last_event_id=${lastEventId}` : "";
      source = new EventSource(`${API_BASE_URL}/events/stream${cursor}`, { withCredentials: true });

      source.onopen = () => {
        reconnectAttempt = 0;
      };

      const receive = (rawEvent: Event) => {
        const message = rawEvent as MessageEvent<string>;
        const parsedEventId = Number(message.lastEventId);
        if (Number.isSafeInteger(parsedEventId) && parsedEventId > lastEventId) {
          lastEventId = parsedEventId;
          try {
            window.sessionStorage.setItem(CURSOR_KEY, String(lastEventId));
          } catch {
            // Storage may be disabled; in-memory replay protection remains active.
          }
        }
        try {
          callback.current(JSON.parse(message.data) as ControlPlaneEvent);
        } catch {
          // Ignore keepalives and malformed frames; the stream remains usable.
        }
      };
      source.onmessage = receive;
      for (const eventName of [
        "incident.created",
        "incident.state_changed",
        "incident.event",
        "remediation.progress",
        "verification.progress",
        "approval.changed",
        "security.event",
        "security.containment",
        "incident_lab.execution",
        "finops.recommendation",
        "finops.pr_created",
        "incident.ai_diagnosis",
        "incident.ai_diagnosis_queued",
        "incident.ai_action_evaluated",
        "incident.source_correlated",
        "incident.source_correlation_unavailable",
        "incident.github_issue",
        "notification.dashboard",
      ]) {
        source.addEventListener(eventName, receive);
      }

      source.onerror = () => {
        source?.close();
        if (stopped) return;
        const delay = Math.min(30_000, 1_000 * 2 ** reconnectAttempt);
        reconnectAttempt = Math.min(reconnectAttempt + 1, 5);
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      source?.close();
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
    };
  }, [enabled]);
}
