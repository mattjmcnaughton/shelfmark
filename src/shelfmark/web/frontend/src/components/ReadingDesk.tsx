import React, { useState as S, useEffect, useRef } from "react";
import {
  LibraryBig,
  Inbox,
  Bookmark,
  Archive,
  Rss,
  RefreshCw,
  Plus,
  Keyboard,
  Expand,
  Shrink,
  Tag as TagIcon,
  ChevronLeft,
  ChevronRight,
  Menu,
  BookOpen,
  Film,
  ArrowUpRight,
  FolderOpen,
} from "lucide-react";
type LiveItem = {
  id: number;
  title: string;
  feed: string;
  author: string;
  tags: string[];
  deck: string;
  body: { text: string; heading: boolean }[];
  video: string;
  arch: boolean;
  saved: boolean;
  url: string;
  date: string;
  sources: string[];
};
type Feed = {
  name: string;
  url: string;
  checked: string;
  error: string | null;
};
type Library = { items: LiveItem[]; feeds: Feed[]; id?: number };
const dateLabel = (date: string) =>
  new Date(date).toLocaleDateString(undefined, { dateStyle: "medium" });

async function request(action = "library", data?: object): Promise<Library> {
  const response = await fetch(
    `/api/${action}`,
    data && {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    },
  );
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Could not reach Shelfmark.");
  return result;
}

export function ReadingDesk() {
  const [{ items, feeds: subscriptions }, set] = S<Library>({
      items: [],
      feeds: [],
    }),
    [view, V] = S("Inbox"),
    [id, I] = S(0),
    [focus, F] = S(false),
    [mobile, M] = S("queue"),
    [modal, D] = S(""),
    [msg, A] = S(""),
    [err, E] = S(""),
    [busy, B] = S(false),
    [loading, L] = S(true),
    [player, P] = S<number>();
  const fs = subscriptions.map((f) => f.url);
  const feedView = subscriptions.find((f) => f.url === view);
  const tagView = view.startsWith("tag:") ? view.slice(4) : "";
  const tags = [...new Set(items.flatMap((x) => x.tags))].sort();
  const viewName = feedView?.name || tagView || view;
  useEffect(() => {
    request()
      .then(set)
      .catch((error) => A(error.message))
      .finally(() => L(false));
  }, []);
  const dlg = useRef<HTMLDialogElement>(null),
    reader = useRef<HTMLElement>(null),
    opener = useRef<HTMLElement | null>(null);
  const filtered = (v: string, arr = items) =>
    arr.filter((x) =>
      v === "Inbox"
        ? !x.arch && !x.saved
        : v === "Saved"
          ? x.saved && !x.arch
          : v === "Archive"
            ? x.arch
            : v.startsWith("tag:")
              ? x.tags.includes(v.slice(4))
              : x.sources.includes(v) && !x.arch,
    );
  const list = filtered(view),
    item = list.find((x) => x.id === id) || list[0],
    pos = list.indexOf(item);
  function choose(v: string) {
    V(v);
    I(filtered(v)[0]?.id ?? -1);
    M("queue");
    F(false);
  }
  function pick(x: LiveItem) {
    I(x.id);
    M("read");
    requestAnimationFrame(() => {
      if (matchMedia("(max-width: 760px)").matches) reader.current?.focus();
    });
  }
  function move(d: number) {
    const x = list[Math.max(0, Math.min(list.length - 1, pos + d))];
    if (x) {
      I(x.id);
      requestAnimationFrame(() => {
        const b = document.querySelector<HTMLElement>(`#row${x.id}`);
        if (b?.offsetWidth) b.focus();
        else reader.current?.focus();
      });
    }
  }
  async function patch(p: Partial<LiveItem>) {
    if (!item) return;
    set(await request("item", { id: item.id, ...p }));
  }
  async function archive() {
    if (!item || busy) return;
    B(true);
    try {
      await patch({ arch: !item.arch, ...(item.arch && { saved: false }) });
      if (!tagView) {
        const next = list[pos + 1] || list[pos - 1];
        I(next?.id ?? -1);
        requestAnimationFrame(() => {
          const b = document.querySelector<HTMLElement>(`#row${next?.id}`);
          if (!focus && b?.offsetWidth) b.focus();
          else reader.current?.focus();
        });
      }
      A(item.arch ? "Returned to Inbox" : "Moved to Archive");
    } catch (error) {
      A((error as Error).message);
    } finally {
      B(false);
    }
  }
  async function save() {
    if (item && !busy) {
      B(true);
      try {
        await patch({
          saved: !item.saved,
          ...(item.arch && !item.saved && { arch: false }),
        });
        A(item.saved ? "Removed from Saved" : "Added to Saved");
      } catch (error) {
        A((error as Error).message);
      } finally {
        B(false);
      }
    }
  }
  async function refresh() {
    if (busy) return;
    B(true);
    try {
      const next = await request("refresh", {});
      set(next);
      A(next.feeds.some((f) => f.error) ? "Some feeds could not refresh." : "Feeds refreshed");
    } catch (error) {
      A((error as Error).message);
    } finally {
      B(false);
    }
  }
  function zoom() {
    F(!focus);
    M("read");
    requestAnimationFrame(() => document.querySelector<HTMLElement>("#zoom")?.focus());
  }
  function open(v: string) {
    if (busy) return;
    opener.current = document.activeElement as HTMLElement;
    E("");
    D(v);
  }
  function close() {
    dlg.current?.close();
    D("");
    requestAnimationFrame(() => {
      if (opener.current?.offsetWidth) opener.current.focus();
      else if (reader.current?.offsetWidth) reader.current.focus();
    });
  }
  useEffect(() => {
    if (modal) {
      dlg.current?.showModal();
      dlg.current?.querySelector<HTMLElement>("input, button")?.focus();
    }
  }, [modal]);
  useEffect(() => {
    if (reader.current) reader.current.scrollTop = 0;
    P(undefined);
    if (!item && focus) {
      F(false);
      M("queue");
    }
  }, [item?.id]);
  useEffect(() => {
    if (msg) {
      const t = setTimeout(() => A(""), 2300);
      return () => clearTimeout(t);
    }
  }, [msg]);
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (modal || e.ctrlKey || e.metaKey || e.altKey || e.target instanceof HTMLInputElement)
        return;
      const acts: Record<string, () => void> = {
        j: () => move(1),
        k: () => move(-1),
        s: save,
        a: archive,
        t: () => item && open("Edit tags"),
        f: () => item && zoom(),
        n: () => open("Save a link"),
        "?": () => open("Keyboard shortcuts"),
        Escape: () => {
          if (focus) zoom();
          else M("queue");
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
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const data = new FormData(e.currentTarget),
      name = String(data.get("name") || "").trim();
    B(true);
    E("");
    try {
      if (modal === "Edit tags") {
        await patch({ tags: name.split(",") });
        A("Tags updated");
      } else {
        const follow = modal === "Add subscription";
        const url = String(data.get("url")).trim();
        const next = await request(follow ? "subscribe" : "save", {
          url,
          name,
        });
        set(next);
        if (follow) {
          V(next.feeds.find((f) => !fs.includes(f.url))?.url || "Inbox");
          I(-1);
          M("queue");
          F(false);
        } else {
          V("Saved");
          I(next.id ?? -1);
          M("read");
        }
        A(follow ? "Subscription added" : "Link saved");
      }
      close();
    } catch (error) {
      E((error as Error).message);
    } finally {
      B(false);
    }
  }
  const fo = [Inbox, Bookmark, Archive];
  return (
    <div className={`workspace ${focus ? "focused" : ""} mobile-${mobile}`}>
      <nav aria-label="Library navigation">
        <div className="brand">
          <LibraryBig size={30} />
          Shelfmark
        </div>
        <div className="deskname">Personal reading desk</div>
        <button className="primary" onClick={() => open("Save a link")}>
          <Plus size={18} />
          Save a link<kbd>N</kbd>
        </button>
        <div className="navscroll">
          <div className="navlabel">Library</div>
          {["Inbox", "Saved", "Archive"].map((v, i) => {
            const Ic = fo[i];
            return (
              <button
                key={v}
                className={"navrow " + (view === v ? "active" : "")}
                aria-current={view === v ? "page" : undefined}
                onClick={() => choose(v)}
              >
                <Ic />
                {v}
                <small>{filtered(v).length}</small>
              </button>
            );
          })}
          <div className="navlabel feeds">
            Subscriptions{" "}
            <button aria-label="Add subscription" onClick={() => open("Add subscription")}>
              <Plus size={17} />
            </button>
          </div>
          {subscriptions.map(({ url: v, name, error }, i) => (
            <button
              className={"navrow " + (view === v ? "active" : "")}
              key={v}
              title={error || v}
              aria-current={view === v ? "page" : undefined}
              onClick={() => choose(v)}
            >
              <span className={"stamp c" + (i % 4)}>{name[0]}</span>
              {name}
            </button>
          ))}
          {tags.length > 0 && <div className="navlabel feeds">Tags</div>}
          {tags.map((tag) => (
            <button
              key={tag}
              className={"navrow " + (tagView === tag ? "active" : "")}
              aria-current={tagView === tag ? "page" : undefined}
              onClick={() => choose(`tag:${tag}`)}
            >
              <TagIcon />
              {tag}
            </button>
          ))}
        </div>
        <div className="navfoot">
          <span className="light" /> Local library
        </div>
      </nav>
      <section className="queue" aria-label="Item queue">
        <header className="qhead">
          <button className="mob" aria-label="Show library" onClick={() => M("nav")}>
            <Menu />
          </button>
          <span className="kicker">Reading desk</span>
          <button
            className="refresh"
            disabled={busy || !fs.length}
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
            {feedView.error || `Checked ${new Date(feedView.checked).toLocaleString()}`}
          </p>
        )}
        <div className="rows">
          {list.map((x, i) => (
            <React.Fragment key={x.id}>
              {(!i || dateLabel(list[i - 1].date) !== dateLabel(x.date)) && (
                <div className="day">{dateLabel(x.date)}</div>
              )}
              <button
                className={"row " + (item?.id === x.id ? "current" : "")}
                id={"row" + x.id}
                aria-current={item?.id === x.id ? "true" : undefined}
                onClick={() => pick(x)}
              >
                <div className="source">
                  <i className={"spot c" + (Math.max(0, fs.indexOf(x.sources[0])) % 4)} />
                  {x.feed}
                  {x.saved && <Bookmark size={12} />}
                </div>
                <strong>{x.title}</strong>
                <span className="kind">
                  {x.video ? <Film /> : <BookOpen />}
                  {x.video ? "Video" : "Article"}
                </span>
              </button>
            </React.Fragment>
          ))}
          {!list.length && (
            <p className="empty">
              {loading
                ? "Loading your library…"
                : feedView
                  ? "No feed entries yet. Try refreshing."
                  : "No items here yet."}
            </p>
          )}
        </div>
        <button className="hint" onClick={() => open("Keyboard shortcuts")}>
          <Keyboard size={16} /> Keyboard shortcuts <kbd>?</kbd>
        </button>
      </section>
      <main>
        <header className="tools">
          <button
            className="mob"
            onClick={() => {
              F(false);
              M("queue");
            }}
          >
            <ChevronLeft />
            List
          </button>
          <span className="crumb">
            {focus ? "Reading view" : viewName}{" "}
            {item && (
              <>
                <span>/</span>
                {item.video ? "Video" : "Article"}
              </>
            )}
          </span>
          <div className="toolbar">
            {item && (
              <>
                <button
                  disabled={busy}
                  title="Save (S)"
                  aria-label="Save item"
                  aria-pressed={item.saved}
                  onClick={save}
                >
                  <Bookmark fill={item.saved ? "currentColor" : "none"} />
                </button>
                <button
                  disabled={busy}
                  title="Edit tags (T)"
                  aria-label="Edit tags"
                  onClick={() => open("Edit tags")}
                >
                  <TagIcon />
                </button>
                <button
                  disabled={busy}
                  title={item.arch ? "Return to Inbox (A)" : "Archive (A)"}
                  aria-label={item.arch ? "Return to Inbox" : "Archive item"}
                  onClick={archive}
                >
                  <Archive />
                </button>
                <button className="focusbt" id="zoom" onClick={zoom}>
                  {focus ? <Shrink /> : <Expand />}
                  {focus ? "Exit focus" : "Focus"}
                </button>
              </>
            )}
          </div>
        </header>
        <article ref={reader} tabIndex={-1}>
          {item ? (
            <div className="sheet">
              <div className="folio">
                <span>
                  <i className={"spot c" + (Math.max(0, fs.indexOf(item.sources[0])) % 4)} />
                  {item.feed}
                </span>
                <span>
                  {item.video
                    ? "Video"
                    : item.sources.length && !item.saved
                      ? "Feed copy"
                      : "Reading copy"}
                </span>
              </div>
              <h2>{item.title}</h2>
              {item.deck && <p className="deck">{item.deck}</p>}
              <div className="by">
                {item.author && (
                  <>
                    {item.author}
                    <span> / </span>
                  </>
                )}
                {dateLabel(item.date)}
              </div>
              {item.video &&
                (player === item.id ? (
                  <iframe
                    className="player"
                    title={`YouTube: ${item.title}`}
                    src={`https://www.youtube-nocookie.com/embed/${item.video}?autoplay=1`}
                    allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                    allowFullScreen
                    referrerPolicy="strict-origin-when-cross-origin"
                  />
                ) : (
                  <button className="player poster" onClick={() => P(item.id)}>
                    <Film /> Load YouTube player
                  </button>
                ))}
              <div className="prose">
                {!item.video &&
                  (item.body.length ? (
                    item.body.map(({ text, heading }, i) =>
                      heading ? <h3 key={i}>{text}</h3> : <p key={i}>{text}</p>,
                    )
                  ) : (
                    <p>No readable copy from this source. Your link is still saved here.</p>
                  ))}
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.video ? "Open in YouTube" : "Open original"} <ArrowUpRight size={14} />
                </a>
              </div>
              <div className="tags">
                <TagIcon size={15} />
                {item.tags.join("  /  ") || "No tags"}
                <button disabled={busy} onClick={() => open("Edit tags")}>
                  Edit tags
                </button>
              </div>
            </div>
          ) : (
            <div className="blank">
              <FolderOpen />
              <h2>{loading ? "Opening your desk…" : "Your desk is clear."}</h2>
              {!loading && (
                <p>Save an article or YouTube link, or follow a feed to start reading.</p>
              )}
              {!loading && (
                <div className="start">
                  <button onClick={() => open("Save a link")}>Save a link</button>
                  <button onClick={() => open("Add subscription")}>
                    <Rss size={15} /> Follow a feed
                  </button>
                </div>
              )}
              <button
                onClick={() => {
                  F(false);
                  M("queue");
                }}
                className="mob"
              >
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
            <button disabled={pos <= 0} onClick={() => move(-1)}>
              <ChevronLeft />
              Previous
            </button>
            <button disabled={pos >= list.length - 1} onClick={() => move(1)}>
              Next
              <ChevronRight />
            </button>
          </div>
        </footer>
      </main>
      <div role="status" className={msg ? "toast" : ""}>
        {msg}
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
                {[
                  ["J / K", "Next / previous item"],
                  ["S", "Toggle saved"],
                  ["T", "Edit tags"],
                  ["A", "Archive / return to Inbox"],
                  ["F", "Toggle focus view"],
                  ["N", "Save a link"],
                  ["?", "Show shortcuts"],
                  ["Esc", "Close dialog or leave focus"],
                ].map(([k, v]) => (
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
                <div role="alert">{err}</div>
                <div className="actions">
                  <button type="button" disabled={busy} onClick={close}>
                    Cancel
                  </button>
                  <button className="confirm" disabled={busy}>
                    {busy
                      ? "Working…"
                      : modal === "Edit tags"
                        ? "Save tags"
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
