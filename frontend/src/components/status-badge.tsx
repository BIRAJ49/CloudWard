import type { Tone } from "../types";

interface StatusBadgeProps {
  label: string;
  tone?: Tone;
  dot?: boolean;
}

export function StatusBadge({
  label,
  tone = "neutral",
  dot = false,
}: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${tone}`} data-tone={tone}>
      {dot ? <span className="status-badge__dot" aria-hidden="true" /> : <span className="status-badge__rule" aria-hidden="true" />}
      <span className="status-badge__label">{label}</span>
    </span>
  );
}
