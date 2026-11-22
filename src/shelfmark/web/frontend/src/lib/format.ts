export const dateLabel = (date: string | null) =>
  date ? new Date(date).toLocaleDateString(undefined, { dateStyle: "medium" }) : "Undated";

/** The source line for an item, falling back to the link's host or the queue it is in. */
export function sourceLabel(item: { source: string; url: string | null; trying: boolean }) {
  if (item.source) return item.source;
  if (item.url) {
    try {
      return new URL(item.url).hostname.replace(/^www\./, "");
    } catch {
      return item.url;
    }
  }
  return item.trying ? "To try" : "Note";
}
