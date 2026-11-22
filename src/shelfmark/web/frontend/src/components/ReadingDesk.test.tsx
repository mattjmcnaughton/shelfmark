import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { ItemSummary } from "../lib/api";
import { ReadingDesk } from "./ReadingDesk";

// jsdom has no modal dialog support; open and close the element like a browser would.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.open = true;
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.open = false;
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** An in-memory Shelfmark server implementing the parts of docs/api.md the desk uses. */
function fakeServer(items: ItemSummary[]) {
  const inView = (x: ItemSummary, view: string | null) =>
    view === "inbox"
      ? !x.saved && !x.trying && !x.archived
      : view === "saved"
        ? x.saved && !x.archived
        : view === "try"
          ? x.trying && !x.archived
          : view === "archive" && x.archived;
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://desk.test");
    const method = init?.method ?? "GET";
    const id = Number(url.pathname.split("/")[3]);
    const item = items.find((x) => x.id === id);
    if (url.pathname === "/api/library") {
      const count = (view: string) => items.filter((x) => inView(x, view)).length;
      return json({
        user: { name: "Ada", can_sign_out: true },
        feeds: [],
        tags: [],
        counts: {
          inbox: count("inbox"),
          saved: count("saved"),
          try: count("try"),
          archive: count("archive"),
        },
      });
    }
    if (url.pathname === "/api/items" && method === "POST") {
      const { queue, url: link, title, note } = JSON.parse(String(init?.body));
      if (!link && !title) return json({ detail: "Give it a name or a link." }, 422);
      const added: ItemSummary = {
        ...article(Math.max(0, ...items.map((x) => x.id)) + 1, title ?? link),
        url: link ?? null,
        kind: link ? "article" : "thing",
        source: "",
        copy: link ? "link" : "none",
        saved: queue === "saved",
        trying: queue === "try",
        note: note ?? "",
      };
      items.push(added);
      return json({ ...added, body: [] }, 201);
    }
    if (url.pathname === "/api/items") {
      const view = url.searchParams.get("view");
      const newestFirst = (a: ItemSummary, b: ItemSummary) => b.id - a.id;
      return json({ items: items.filter((x) => inView(x, view)).sort(newestFirst) });
    }
    if (!item) return json({ detail: "Not found." }, 404);
    if (method === "PATCH") {
      const changes = JSON.parse(String(init?.body));
      const unarchive = changes.saved || changes.trying;
      Object.assign(item, changes, unarchive ? { archived: false } : {});
    }
    const body = item.url ? [{ text: `Body of ${item.title}`, heading: false }] : [];
    return json({ ...item, body });
  };
}

const article = (id: number, title: string): ItemSummary => ({
  id,
  url: `https://example.com/${id}`,
  kind: "article",
  title,
  source: "Example",
  author: null,
  deck: null,
  video_id: null,
  published_at: `2026-11-${10 + id}T12:00:00Z`,
  saved: false,
  trying: false,
  archived: false,
  note: "",
  tags: [],
  feed_ids: [],
  copy: "feed",
});

function renderDesk(fetch: typeof globalThis.fetch) {
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ReadingDesk />
    </QueryClientProvider>,
  );
}

const navCount = (label: string) =>
  within(screen.getByRole("navigation"))
    .getByRole("button", { name: new RegExp(`^${label}`) })
    .querySelector("small")?.textContent;

const rowTitles = () =>
  Array.from(document.querySelectorAll(".row strong"), (el) => el.textContent);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("pressing S moves the selected Inbox item to Saved", async () => {
  renderDesk(fakeServer([article(1, "Older post"), article(2, "Newer post")]));

  await screen.findByText("Body of Newer post");
  expect(rowTitles()).toEqual(["Newer post", "Older post"]);

  fireEvent.keyDown(document.body, { key: "s" });

  await waitFor(() => expect(rowTitles()).toEqual(["Older post"]));
  expect(navCount("Inbox")).toBe("1");
  expect(navCount("Saved")).toBe("1");

  fireEvent.click(within(screen.getByRole("navigation")).getByRole("button", { name: /^Saved/ }));
  await waitFor(() => expect(rowTitles()).toEqual(["Newer post"]));
});

test("pressing I adds a named thing with a note to To try", async () => {
  renderDesk(fakeServer([article(1, "A post")]));
  await screen.findByText("Body of A post");

  fireEvent.keyDown(document.body, { key: "i" });
  const dialog = await screen.findByRole("dialog", { name: "Add something to try" });
  fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "omnigent" } });
  fireEvent.change(within(dialog).getByLabelText("Why try it? (optional)"), {
    target: { value: "Agent harness\nthat looked promising" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Add to To try" }));

  await waitFor(() => expect(rowTitles()).toEqual(["omnigent"]));
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("To try");
  expect(navCount("To try")).toBe("1");
  expect(navCount("Inbox")).toBe("1");
  const note = screen.getByRole("region", { name: "Why try it" });
  expect(note.querySelector("p")?.textContent).toBe("Agent harness\nthat looked promising");
  expect(screen.queryByRole("link", { name: /Open original/ })).toBeNull();
});

test("an unauthenticated visitor is asked to sign in", async () => {
  renderDesk(async () =>
    json({ detail: "Sign in to continue.", sign_in_url: "/auth/signin?returnTo=/" }, 401),
  );

  const link = await screen.findByRole("link", { name: "Sign in" });
  expect(link.getAttribute("href")).toBe("/auth/signin?returnTo=/");
});
