// Timecode formatting/parsing for the cutter.
// Port of the tkinter tool's fmt_time/parse_time, with the "60.000" rounding
// artifact of the Python version removed (we derive from whole milliseconds).

/** `MM:SS.mmm` (or `HH:MM:SS.mmm` past an hour). Negative/NaN clamps to zero. */
export function fmtTime(sec: number): string {
  const total = Number.isFinite(sec) && sec > 0 ? Math.round(sec * 1000) : 0;
  const m = Math.floor(total / 60000);
  const s = (total % 60000) / 1000;
  return `${String(m).padStart(2, "0")}:${s.toFixed(3).padStart(6, "0")}`;
}

/**
 * Parse `00:05.200`, `1:02:03.5` or a bare `5.2` into seconds.
 * Returns `null` on anything unparseable so callers can surface the error.
 */
export function parseTime(input: string): number | null {
  const s = input.trim();
  if (!s) return 0;
  const parts = s.split(":");
  if (parts.length > 1) {
    const nums = parts.map((p) => Number(p.trim()));
    if (nums.some((n) => !Number.isFinite(n))) return null;
    if (parts.length === 2) return nums[0]! * 60 + nums[1]!;
    if (parts.length === 3) return nums[0]! * 3600 + nums[1]! * 60 + nums[2]!;
    return nums[nums.length - 1]!;
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** `1.234 s` — the compact duration shown next to the selection fields. */
export const fmtSeconds = (sec: number): string =>
  `${(Number.isFinite(sec) ? sec : 0).toFixed(3)} s`;
