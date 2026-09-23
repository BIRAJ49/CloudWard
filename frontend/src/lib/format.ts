import type { DependencyCheck, Incident, Service, Tone } from "../types";

const terminalStates = new Set(["RESOLVED", "BLOCKED", "ESCALATED"]);

export function serviceName(incident: Incident, services: Service[] = []): string {
  if (incident.service_name) return incident.service_name;
  if (typeof incident.service === "string") return incident.service;
  if (incident.service?.name) return incident.service.name;
  return services.find((service) => service.id === incident.service_id)?.name ?? "Unassigned service";
}

export function formatDate(value?: string | null): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatRelative(value?: string): string {
  if (!value) return "Unknown time";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;
  const deltaMinutes = Math.round((timestamp - Date.now()) / 60_000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(deltaMinutes) < 60) return formatter.format(deltaMinutes, "minute");
  const hours = Math.round(deltaMinutes / 60);
  if (Math.abs(hours) < 48) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

export function humanize(value?: string): string {
  if (!value) return "Unknown";
  return value
    .toLowerCase()
    .split(/[_.\-\s]+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function stateTone(state?: string): Tone {
  const normalized = state?.toUpperCase();
  if (
    normalized === "RESOLVED" ||
    normalized === "HEALTHY" ||
    normalized === "READY" ||
    normalized === "UP" ||
    normalized === "ALIVE" ||
    normalized === "OPERATIONAL" ||
    normalized === "CONNECTED" ||
    normalized === "SUCCEEDED" ||
    normalized === "APPROVED" ||
    normalized === "APPLIED" ||
    normalized === "REMOVED" ||
    normalized === "SENT"
  ) {
    return "good";
  }
  if (
    normalized === "ESCALATED" ||
    normalized === "BLOCKED" ||
    normalized === "UNHEALTHY" ||
    normalized === "FAILED" ||
    normalized === "REJECTED" ||
    normalized === "EXPIRED" ||
    normalized === "DOWN" ||
    normalized === "NOT_READY"
  ) {
    return "bad";
  }
  if (
    normalized === "AWAITING_APPROVAL" ||
    normalized === "ROLLBACK" ||
    normalized === "DEGRADED" ||
    normalized === "STALE" ||
    normalized === "CONTAINED" ||
    normalized === "PENDING"
  ) {
    return "warn";
  }
  if (!normalized || normalized === "UNKNOWN" || normalized === "UNAVAILABLE") {
    return "neutral";
  }
  return "info";
}

export function isActiveIncident(incident: Incident): boolean {
  return !terminalStates.has(incident.state.toUpperCase());
}

export function normalizedCheck(
  value: DependencyCheck | string | boolean | undefined,
): { label: string; tone: Tone; detail?: string } {
  if (typeof value === "boolean") {
    return { label: value ? "Healthy" : "Unhealthy", tone: value ? "good" : "bad" };
  }
  if (typeof value === "string") {
    return { label: humanize(value), tone: stateTone(value) };
  }
  if (!value) return { label: "Unavailable", tone: "neutral" };
  const status = value.status ?? (value.healthy === true ? "healthy" : value.healthy === false ? "unhealthy" : "unknown");
  return {
    label: humanize(status),
    tone: stateTone(status),
    detail: value.message,
  };
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
