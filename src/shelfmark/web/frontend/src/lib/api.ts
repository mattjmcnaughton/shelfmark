// Typed client for the Shelfmark API (see docs/api.md).

export type Feed = {
  id: number;
  url: string;
  title: string;
  checked_at: string | null;
  error: string | null;
};

export type Library = {
  user: { name: string; can_sign_out: boolean };
  feeds: Feed[];
  tags: string[];
  counts: { inbox: number; saved: number; try: number; archive: number };
};

export type ItemSummary = {
  id: number;
  /** `null` for a thing to try that has no link. */
  url: string | null;
  /** A `thing` is something to try: a name, link, description, note, and tags. */
  kind: "article" | "video" | "thing";
  title: string;
  source: string;
  author: string | null;
  deck: string | null;
  video_id: string | null;
  published_at: string | null;
  saved: boolean;
  archived: boolean;
  /** The user's own plain-text note, such as why something is worth trying. */
  note: string;
  tags: string[];
  feed_ids: number[];
  copy: "feed" | "extracted" | "link" | "none";
};

export type ItemDetail = ItemSummary & { body: { text: string; heading: boolean }[] };

export type ItemPatch = Partial<Pick<ItemSummary, "saved" | "archived" | "tags" | "note">>;

export type View =
  | { kind: "inbox" }
  | { kind: "saved" }
  | { kind: "try" }
  | { kind: "archive" }
  | { kind: "feed"; feedId: number }
  | { kind: "tag"; tag: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly body: Record<string, unknown> = {},
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

const API_BASE = import.meta.env.VITE_API_URL ?? "";

function detailOf(body: Record<string, unknown>, status: number): string {
  if (typeof body.detail === "string") return body.detail;
  // FastAPI validation errors are a list of {loc, msg, type}.
  if (Array.isArray(body.detail)) return "Check the form and try again.";
  return status >= 500 ? "Shelfmark is unavailable right now." : "Could not reach Shelfmark.";
}

export async function api<T>(path: string, method = "GET", data?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "same-origin",
    headers: data === undefined ? undefined : { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new ApiError(response.status, detailOf(body ?? {}, response.status), body);
  return body as T;
}

export function itemsPath(view: View): string {
  const params = new URLSearchParams({ view: view.kind });
  if (view.kind === "feed") params.set("feed_id", String(view.feedId));
  if (view.kind === "tag") params.set("tag", view.tag);
  return `/api/items?${params}`;
}
