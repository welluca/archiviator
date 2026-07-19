/** Amount + optional currency code: "1'249.50 CHF", "80 EUR", "12.5". */
export function formatMoney(value: number, currency?: string | null): string {
  if (!Number.isFinite(value)) return '—';
  const num = value.toLocaleString(undefined, {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${num} ${currency}` : num;
}

/** Compact quantity: strips float noise (2.5 stays, 3.0 -> 3). */
export function formatQuantity(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
}

/** Human-readable byte size: 812 B, 24.3 KB, 1.8 MB… */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = -1;
  do {
    value /= 1024;
    unit++;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}
