import { ArrowUpRight, Film, Tag as TagIcon } from "lucide-react";
import { useState } from "react";
import type { ItemDetail, ItemSummary } from "../lib/api";
import { dateLabel, sourceLabel } from "../lib/format";

const COPY_LABEL = {
  feed: "Feed copy",
  extracted: "Reading copy",
  link: "Link only",
  none: "No link",
} as const;

type Props = {
  item: ItemSummary;
  detail: ItemDetail | undefined;
  detailError: string | undefined;
  spot: string;
  busy: boolean;
  onEditTags: () => void;
  onEditNote: () => void;
};

/** The reader's sheet for one item. Key it by item id so the player resets per item. */
export function ItemSheet({
  item,
  detail,
  detailError,
  spot,
  busy,
  onEditTags,
  onEditNote,
}: Props) {
  const [player, setPlayer] = useState(false);
  const isVideo = item.kind === "video";
  const isThing = item.kind === "thing";
  const hasLink = item.url !== null && item.copy !== "none";
  const body = detail?.id === item.id ? detail.body : undefined;
  return (
    <div className="sheet">
      <div className="folio">
        <span>
          <i className={`spot ${spot}`} />
          {sourceLabel(item)}
        </span>
        <span>{isVideo ? "Video" : isThing ? "Thing to try" : COPY_LABEL[item.copy]}</span>
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
        {dateLabel(item.published_at)}
      </div>
      {item.note.trim() && (
        <section className="note" aria-label={isThing ? "Why try it" : "Note"}>
          <h3>{isThing ? "Why try it" : "Note"}</h3>
          <p>{item.note}</p>
        </section>
      )}
      {isVideo &&
        item.video_id &&
        (player ? (
          <iframe
            className="player"
            title={`YouTube: ${item.title}`}
            src={`https://www.youtube-nocookie.com/embed/${item.video_id}?autoplay=1`}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <button type="button" className="player poster" onClick={() => setPlayer(true)}>
            <Film /> Load YouTube player
          </button>
        ))}
      <div className="prose">
        {isThing
          ? !hasLink && !item.note.trim() && !item.deck && <p>Just a reminder — no link saved.</p>
          : !isVideo &&
            (item.copy === "link" || body?.length === 0 ? (
              <p>No readable copy from this source. Your link is still saved here.</p>
            ) : body ? (
              body.map((block, i) =>
                block.heading ? (
                  // biome-ignore lint/suspicious/noArrayIndexKey: body blocks are a static, ordered list
                  <h3 key={i}>{block.text}</h3>
                ) : (
                  // biome-ignore lint/suspicious/noArrayIndexKey: body blocks are a static, ordered list
                  <p key={i}>{block.text}</p>
                ),
              )
            ) : (
              detailError && <p>{detailError}</p>
            ))}
        {hasLink && item.url && (
          <a href={item.url} target="_blank" rel="noreferrer">
            {isVideo ? "Open in YouTube" : isThing ? "Open link" : "Open original"}{" "}
            <ArrowUpRight size={14} />
          </a>
        )}
      </div>
      <div className="tags">
        <TagIcon size={15} />
        {item.tags.join("  /  ") || "No tags"}
        <button type="button" disabled={busy} onClick={onEditTags}>
          Edit tags
        </button>
        <button type="button" disabled={busy} onClick={onEditNote}>
          Edit note
        </button>
      </div>
    </div>
  );
}
