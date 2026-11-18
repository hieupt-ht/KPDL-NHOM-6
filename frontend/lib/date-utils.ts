/** Calendar dates used by the dashboard are Vietnamese days, not UTC labels. */
export function vietnamDay(value: string | number | Date): string {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(value));
  const get = (name: string) => parts.find(part => part.type === name)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function apiDateRange(range: { start?: string; end?: string }): Record<string, string | undefined> {
  function bound(value: string | undefined, end: boolean): string | undefined {
    if (!value) return undefined;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const date = new Date(`${value}T00:00:00Z`);
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value) throw new Error("Ngày lọc không hợp lệ.");
    if (end) date.setUTCDate(date.getUTCDate() + 1);
    return `${date.toISOString().slice(0, 10)}T00:00:00+07:00`;
  }
  return { start: bound(range.start, false), end: bound(range.end, true) };
}
