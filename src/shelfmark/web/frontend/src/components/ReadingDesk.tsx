import { useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Bookmark,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Expand,
  Film,
  FlaskConical,
  FolderOpen,
  Inbox,
  Keyboard,
  LibraryBig,
  Menu,
  Plus,
  RefreshCw,
  Rss,
  Shrink,
  Tag as TagIcon,
} from "lucide-react";
import { type FormEvent, Fragment, useEffect, useRef, useState } from "react";
import { keys, useItem, useItems, useLibrary } from "../hooks/useDeskQueries";
import {
  ApiError,
  type Feed,
  type ItemDetail,
  type ItemPatch,
  type ItemSummary,
  type View,
  api,
} from "../lib/api";
import { dateLabel, sourceLabel } from "../lib/format";
import { AuthScreen, SignOutForm } from "./AuthScreen";
import { ItemSheet } from "./ItemSheet";

type Modal =
  | ""
  | "Save a link"
  | "Add something to try"
  | "Add subscription"
  | "Edit tags"
  | "Edit note"
  | "Keyboard shortcuts";

const NOTE_MAX = 2000;

const LIBRARY_VIEWS = [
  { kind: "inbox", label: "Inbox", Icon: Inbox },
  { kind: "saved", label: "Saved", Icon: Bookmark },
  { kind: "try", label: "To try", Icon: FlaskConical },
  { kind: "archive", label: "Archive", Icon: Archive },
] as const;

const SHORTCUTS = [
  ["J / K", "Next / previous item"],
  ["S", "Toggle saved"],
  ["E", "Toggle To try"],
  ["T", "Edit tags"],
  ["A", "Archive / restore"],
  ["F", "Toggle focus view"],
  ["N", "Save a link"],
  ["I", "Add something to try"],
  ["?", "Show shortcuts"],
  ["Esc", "Close dialog or leave focus"],
];

const kindLabel = (x: ItemSummary) =>
  x.trying ? "To try" : x.kind === "video" ? "Video" : x.kind === "thing" ? "Thing" : "Article";

/** Where restoring an archived item puts it (see docs/api.md). */
const restoreLabel = (x: ItemSummary) =>
  x.trying ? "Restore to To try" : x.saved ? "Restore to Saved" : "Return to Inbox";

const sameView = (a: View, b: View) => JSON.stringify(a) === JSON.stringify(b);

export function ReadingDesk() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>({ kind: "inbox" });
  const [selectedId, setSelectedId] = useState(-1);
  const [focus, setFocus] = useState(false);
  const [mobile, setMobile] = useState<"nav" | "queue" | "read">("queue");
  const [modal, setModal] = useState<Modal>("");
  const [toast, setToast] = useState("");
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);

  const library = useLibrary();
  const items = useItems(view, library.isSuccess);
  const list = items.data ?? [];
  const item = list.find((x) => x.id === selectedId) ?? list[0];
  const pos = item ? list.indexOf(item) : -1;
  const detail = useItem(item?.id);

  const dlg = useRef<HTMLDialogElement>(null);
  const reader = useRef<HTMLElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  const feeds = library.data?.feeds ?? [];
  const tags = library.data?.tags ?? [];
  const user = library.data?.user;
  const feedView = view.kind === "feed" ? feeds.find((f) => f.id === view.feedId) : undefined;
  const tagView = view.kind === "tag" ? view.tag : "";
  const viewName =
    view.kind === "feed"
      ? (feedView?.title ?? "Feed")
      : view.kind === "tag"
        ? view.tag
        : LIBRARY_VIEWS.find((v) => v.kind === view.kind)?.label;
  const loading = library.isPending || items.isLoading;
  const loadError = library.error?.message ?? items.error?.message;
  const spot = (x: ItemSummary) =>
    `c${
      Math.max(
        0,
        feeds.findIndex((f) => f.id === x.feed_ids[0]),
      ) % 4
    }`;

  async function syncServerState() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: keys.library }),
      queryClient.invalidateQueries({ queryKey: keys.items }),
    ]);
  }

  /** Runs one mutation at a time; shows its message as a toast and errors via onError. */
  async function run(action: () => Promise<string | undefined>, onError = setToast) {
    if (busy) return false;
    setBusy(true);
    try {
      const message = await action();
      if (message) setToast(message);
      return true;
    } catch (error) {
      onError((error as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function patch(target: ItemSummary, changes: ItemPatch) {
    const updated = await api<ItemDetail>(`/api/items/${target.id}`, "PATCH", changes);
    queryClient.setQueryData(keys.item(updated.id), updated);
  }

  function choose(next: View) {
    setView(next);
    setSelectedId(-1);
    setMobile("queue");
    setFocus(false);
  }
  function pick(x: ItemSummary) {
    setSelectedId(x.id);
    setMobile("read");
    requestAnimationFrame(() => {
      if (matchMedia("(max-width: 760px)").matches) reader.current?.focus();
    });
  }
  function focusRow(id: number | undefined) {
    requestAnimationFrame(() => {
      const row = document.querySelector<HTMLElement>(`#row${id}`);
      if (!focus && row?.offsetWidth) row.focus();
      else reader.current?.focus();
    });
  }
  function move(delta: number) {
    const x = list[Math.max(0, Math.min(list.length - 1, pos + delta))];
    if (x) {
      setSelectedId(x.id);
      focusRow(x.id);
    }
  }
  function save() {
    if (!item) return;
    const target = item;
    run(async () => {
      await patch(target, { saved: !target.saved });
      await syncServerState();
      return target.saved ? "Removed from Saved" : "Added to Saved";
    });
  }
  function toggleTry() {
    if (!item) return;
    const target = item;
    run(async () => {
      await patch(target, { trying: !target.trying });
      await syncServerState();
      return target.trying ? "Removed from To try" : "Added to To try";
    });
  }
  function archive() {
    if (!item) return;
    const target = item;
    run(async () => {
      await patch(target, { archived: !target.archived });
      // Tag views include archived items, so the item stays put there.
      if (view.kind !== "tag") {
        const next = list[pos + 1] ?? list[pos - 1];
        setSelectedId(next?.id ?? -1);
        focusRow(next?.id);
      }
      await syncServerState();
      if (!target.archived) return target.trying ? "Marked tried" : "Moved to Archive";
      if (target.trying) return "Restored to To try";
      return target.saved ? "Restored to Saved" : "Returned to Inbox";
    });
  }
  function refresh() {
    run(async () => {
      const result = await api<{ feeds: Feed[] }>("/api/feeds/refresh", "POST", {});
      await syncServerState();
      return result.feeds.some((f) => f.error)
        ? "Some feeds could not refresh."
        : "Feeds refreshed";
    });
  }
  function zoom() {
    setFocus(!focus);
    setMobile("read");
    requestAnimationFrame(() => document.querySelector<HTMLElement>("#zoom")?.focus());
  }
  function open(next: Modal) {
    if (busy) return;
    opener.current = document.activeElement as HTMLElement;
    setFormError("");
    setModal(next);
  }
  function close() {
    dlg.current?.close();
    setModal("");
    requestAnimationFrame(() => {
      if (opener.current?.offsetWidth) opener.current.focus();
      else if (reader.current?.offsetWidth) reader.current.focus();
    });
  }
  function backToList() {
    setFocus(false);
    setMobile("queue");
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const name = String(data.get("name") ?? "").trim();
    const url = String(data.get("url") ?? "").trim();
    const note = String(data.get("note") ?? "").trim();
    const kind = modal;
    const target = item;
    setFormError("");
    if (kind === "Add something to try" && !name && !url) {
      setFormError("Give it a name or a link.");
      return;
    }
    const ok = await run(async () => {
      if (kind === "Edit note") {
        if (!target) return;
        await patch(target, { note });
        await syncServerState();
        return "Note saved";
      }
      if (kind === "Edit tags") {
        if (!target) return;
        const next = name.split(",").map((tag) => tag.trim());
        await patch(target, { tags: next.filter(Boolean) });
        await syncServerState();
        return "Tags updated";
      }
      if (kind === "Add subscription") {
        const feed = await api<Feed>("/api/feeds", "POST", { url, title: name || undefined });
        await syncServerState();
        choose({ kind: "feed", feedId: feed.id });
        return "Subscription added";
      }
      const trying = kind === "Add something to try";
      const added = await api<ItemDetail>("/api/items", "POST", {
        queue: trying ? "try" : "saved",
        url: url || undefined,
        title: name || undefined,
        note: note || undefined,
      });
      queryClient.setQueryData(keys.item(added.id), added);
      await syncServerState();
      setView({ kind: trying ? "try" : "saved" });
      setSelectedId(added.id);
      setMobile("read");
      setFocus(false);
      return trying ? "Added to To try" : "Link saved";
    }, setFormError);
    if (ok) close();
  }

  useEffect(() => {
    if (modal) {
      dlg.current?.showModal();
      dlg.current?.querySelector<HTMLElement>("input, textarea, button")?.focus();
    }
  }, [modal]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: start each newly selected item at the top
  useEffect(() => {
    if (reader.current) reader.current.scrollTop = 0;
  }, [item?.id]);
  useEffect(() => {
    if (!item && focus) {
      setFocus(false);
      setMobile("queue");
    }
  }, [item, focus]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 2300);
      return () => clearTimeout(t);
    }
  }, [toast]);
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (
        modal ||
        e.ctrlKey ||
        e.metaKey ||
        e.altKey ||
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;
      const acts: Record<string, () => void> = {
        j: () => move(1),
        k: () => move(-1),
        s: save,
        e: toggleTry,
        a: archive,
        t: () => item && open("Edit tags"),
        f: () => item && zoom(),
        n: () => open("Save a link"),
        i: () => open("Add something to try"),
        "?": () => open("Keyboard shortcuts"),
        Escape: () => {
          if (focus) zoom();
          else setMobile("queue");
        },
      };
      if (acts[e.key]) {
        e.preventDefault();
        acts[e.key]();
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  if (library.error instanceof ApiError && [401, 403, 503].includes(library.error.status)) {
    return <AuthScreen error={library.error} />;
  }

  return (
    <div className={`workspace ${focus ? "focused" : ""} mobile-${mobile}`}>
      <nav aria-label="Library navigation">
        <div className="brand">
          <LibraryBig size={30} />
          Shelfmark
        </div>
        <div className="deskname">Personal reading desk</div>
        <button type="button" className="primary" onClick={() => open("Save a link")}>
          <Plus size={18} />
          Save a link<kbd>N</kbd>
        </button>
        <button type="button" className="secondary" onClick={() => open("Add something to try")}>
          <FlaskConical size={17} />
          Add something to try<kbd>I</kbd>
        </button>
        <div className="navscroll">
          <div className="navlabel">Library</div>
          {LIBRARY_VIEWS.map(({ kind, label, Icon }) => {
            const active = view.kind === kind;
            return (
              <button
                type="button"
                key={kind}
                className={`navrow ${active ? "active" : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={() => choose({ kind })}
              >
                <Icon />
                {label}
                <small>{library.data?.counts[kind] ?? ""}</small>
              </button>
            );
          })}
          <div className="navlabel feeds">
            Subscriptions{" "}
            <button
              type="button"
              aria-label="Add subscription"
              onClick={() => open("Add subscription")}
            >
              <Plus size={17} />
            </button>
          </div>
          {feeds.map((feed, i) => {
            const active = sameView(view, { kind: "feed", feedId: feed.id });
            return (
              <button
                type="button"
                className={`navrow ${active ? "active" : ""}`}
                key={feed.id}
                title={feed.error || feed.url}
                aria-current={active ? "page" : undefined}
                onClick={() => choose({ kind: "feed", feedId: feed.id })}
              >
                <span className={`stamp c${i % 4}`}>{(feed.title || feed.url)[0]}</span>
                {feed.title || feed.url}
              </button>
            );
          })}
          {tags.length > 0 && <div className="navlabel feeds">Tags</div>}
          {tags.map((tag) => (
            <button
              type="button"
              key={tag}
              className={`navrow ${tagView === tag ? "active" : ""}`}
              aria-current={tagView === tag ? "page" : undefined}
              onClick={() => choose({ kind: "tag", tag })}
            >
              <TagIcon />
              {tag}
            </button>
          ))}
        </div>
        <div className="navfoot">
          <span className="light" /> <span className="who">{user?.name}</span>
          {user?.can_sign_out && <SignOutForm />}
        </div>
      </nav>
      <section className="queue" aria-label="Item queue">
        <header className="qhead">
          <button
            type="button"
            className="mob"
            aria-label="Show library"
            onClick={() => setMobile("nav")}
          >
            <Menu />
          </button>
          <span className="kicker">Reading desk</span>
          <button
            type="button"
            className="refresh"
            disabled={busy || !feeds.length}
            onClick={refresh}
            title="Refresh feeds"
            aria-label="Refresh feeds"
          >
            <RefreshCw size={16} />
          </button>
        </header>
        <div className="qtitle">
          <h1>{viewName}</h1>
          <b>{list.length}</b>
        </div>
        {feedView && (
          <p className="feedstatus">
            {feedView.error ||
              (feedView.checked_at
                ? `Checked ${new Date(feedView.checked_at).toLocaleString()}`
                : "Not checked yet")}
          </p>
        )}
        <div className="rows">
          {list.map((x, i) => (
            <Fragment key={x.id}>
              {(!i || dateLabel(list[i - 1].published_at) !== dateLabel(x.published_at)) && (
                <div className="day">{dateLabel(x.published_at)}</div>
              )}
              <button
                type="button"
                className={`row ${item?.id === x.id ? "current" : ""}`}
                id={`row${x.id}`}
                aria-current={item?.id === x.id ? "true" : undefined}
                onClick={() => pick(x)}
              >
                <div className="source">
                  <i className={`spot ${spot(x)}`} />
                  {sourceLabel(x)}
                  {x.saved && <Bookmark size={12} />}
                </div>
                <strong>{x.title}</strong>
                <span className="kind">
                  {x.trying || x.kind === "thing" ? (
                    <FlaskConical />
                  ) : x.kind === "video" ? (
                    <Film />
                  ) : (
                    <BookOpen />
                  )}
                  {kindLabel(x)}
                </span>
              </button>
            </Fragment>
          ))}
          {!list.length && (
            <p className="empty">
              {loading
                ? "Loading your library…"
                : loadError
                  ? loadError
                  : feedView
                    ? "No feed entries yet. Try refreshing."
                    : view.kind === "try"
                      ? "Nothing to try yet. Press I to add something."
                      : "No items here yet."}
            </p>
          )}
        </div>
        <button type="button" className="hint" onClick={() => open("Keyboard shortcuts")}>
          <Keyboard size={16} /> Keyboard shortcuts <kbd>?</kbd>
        </button>
      </section>
      <main>
        <header className="tools">
          <button type="button" className="mob" onClick={backToList}>
            <ChevronLeft />
            List
          </button>
          <span className="crumb">
            {focus ? "Reading view" : viewName}{" "}
            {item && (
              <>
                <span>/</span>
                {kindLabel(item)}
              </>
            )}
          </span>
          <div className="toolbar">
            {item && (
              <>
                <button
                  type="button"
                  disabled={busy}
                  title="Save (S)"
                  aria-label="Save item"
                  aria-pressed={item.saved}
                  onClick={save}
                >
                  <Bookmark fill={item.saved ? "currentColor" : "none"} />
                </button>
                <button
                  type="button"
                  disabled={busy}
                  title="To try (E)"
                  aria-label="To try"
                  aria-pressed={item.trying}
                  onClick={toggleTry}
                >
                  <FlaskConical fill={item.trying ? "currentColor" : "none"} />
                </button>
                <button
                  type="button"
                  disabled={busy}
                  title="Edit tags (T)"
                  aria-label="Edit tags"
                  onClick={() => open("Edit tags")}
                >
                  <TagIcon />
                </button>
                <button
                  type="button"
                  disabled={busy}
                  title={
                    item.archived
                      ? `${restoreLabel(item)} (A)`
                      : item.trying
                        ? "Mark tried (A)"
                        : "Archive (A)"
                  }
                  aria-label={
                    item.archived ? restoreLabel(item) : item.trying ? "Mark tried" : "Archive item"
                  }
                  onClick={archive}
                >
                  <Archive />
                </button>
                <button type="button" className="focusbt" id="zoom" onClick={zoom}>
                  {focus ? <Shrink /> : <Expand />}
                  {focus ? "Exit focus" : "Focus"}
                </button>
              </>
            )}
          </div>
        </header>
        <article ref={reader} tabIndex={-1}>
          {item ? (
            <ItemSheet
              key={item.id}
              item={item}
              detail={detail.data}
              detailError={detail.error?.message}
              spot={spot(item)}
              busy={busy}
              onEditTags={() => open("Edit tags")}
              onEditNote={() => open("Edit note")}
            />
          ) : (
            <div className="blank">
              <FolderOpen />
              <h2>{loading ? "Opening your desk…" : "Your desk is clear."}</h2>
              {!loading && (
                <p>
                  Save an article or YouTube link, note something to try, or follow a feed to start
                  reading.
                </p>
              )}
              {!loading && (
                <div className="start">
                  <button type="button" onClick={() => open("Save a link")}>
                    Save a link
                  </button>
                  <button type="button" onClick={() => open("Add something to try")}>
                    <FlaskConical size={15} /> Add something to try
                  </button>
                  <button type="button" onClick={() => open("Add subscription")}>
                    <Rss size={15} /> Follow a feed
                  </button>
                </div>
              )}
              <button type="button" onClick={backToList} className="mob">
                Back to library list
              </button>
            </div>
          )}
        </article>
        <footer>
          <span>
            {item
              ? `${String(pos + 1).padStart(2, "0")} / ${String(list.length).padStart(2, "0")}`
              : "00 / 00"}
          </span>
          <div>
            <button type="button" disabled={pos <= 0} onClick={() => move(-1)}>
              <ChevronLeft />
              Previous
            </button>
            <button type="button" disabled={pos >= list.length - 1} onClick={() => move(1)}>
              Next
              <ChevronRight />
            </button>
          </div>
        </footer>
      </main>
      {/* biome-ignore lint/a11y/useSemanticElements: desk.css styles this live region as div[role=status] */}
      <div role="status" className={toast ? "toast" : ""}>
        {toast}
      </div>
      {modal && (
        <dialog
          ref={dlg}
          onCancel={(e) => {
            e.preventDefault();
            if (!busy) close();
          }}
          aria-labelledby="dialogtitle"
        >
          <form onSubmit={submit}>
            <h2 id="dialogtitle">{modal}</h2>
            {modal === "Keyboard shortcuts" ? (
              <>
                <p>Use these keys anywhere outside a form.</p>
                {SHORTCUTS.map(([k, v]) => (
                  <div className="keyrow" key={k}>
                    <span>{v}</span>
                    <kbd>{k}</kbd>
                  </div>
                ))}
                <button type="button" className="confirm" onClick={close}>
                  Got it
                </button>
              </>
            ) : (
              <>
                {modal === "Edit tags" ? (
                  <>
                    <p>Separate tags with commas. Clear the field to remove all tags.</p>
                    <label>
                      Tags
                      <input name="name" defaultValue={item?.tags.join(", ")} autoComplete="off" />
                    </label>
                  </>
                ) : modal === "Edit note" ? (
                  <>
                    <p>
                      {item?.trying
                        ? "Why is this worth trying? Plain text, up to 2000 characters."
                        : "A private note for this item. Plain text, up to 2000 characters."}
                    </p>
                    <label>
                      Note
                      <textarea
                        name="note"
                        rows={6}
                        maxLength={NOTE_MAX}
                        defaultValue={item?.note}
                      />
                    </label>
                  </>
                ) : modal === "Add something to try" ? (
                  <>
                    <p>
                      Note a tool, repo, skill, or idea to try later. With a link, Shelfmark will
                      also fetch a readable copy.
                    </p>
                    <label>
                      Name
                      <input name="name" autoComplete="off" placeholder="t3code" />
                    </label>
                    <label>
                      Link (optional)
                      <input name="url" placeholder="https://…" />
                    </label>
                    <label>
                      Why try it? (optional)
                      <textarea name="note" rows={4} maxLength={NOTE_MAX} />
                    </label>
                  </>
                ) : (
                  <>
                    <p>
                      {modal === "Save a link"
                        ? "Save an article or YouTube link. Shelfmark will try to extract a clean copy of the article."
                        : "Paste an RSS or Atom feed URL to fetch its recent posts."}
                    </p>
                    <label>
                      {modal === "Save a link" ? "Link URL" : "RSS feed URL"}
                      <input required name="url" placeholder="https://…" />
                    </label>
                    <label>
                      {modal === "Save a link" ? "Title" : "Subscription name"} (optional)
                      <input name="name" />
                    </label>
                  </>
                )}
                <div role="alert">{formError}</div>
                <div className="actions">
                  <button type="button" disabled={busy} onClick={close}>
                    Cancel
                  </button>
                  <button type="submit" className="confirm" disabled={busy}>
                    {busy
                      ? "Working…"
                      : modal === "Edit tags"
                        ? "Save tags"
                        : modal === "Edit note"
                          ? "Save note"
                          : modal === "Add something to try"
                            ? "Add to To try"
                            : modal === "Save a link"
                              ? "Save link"
                              : "Add feed"}
                  </button>
                </div>
              </>
            )}
          </form>
        </dialog>
      )}
    </div>
  );
}
