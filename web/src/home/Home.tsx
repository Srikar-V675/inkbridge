import { useCallback, useEffect, useMemo, useState } from "react";
import { navigate, onLinkClick } from "../lib/nav";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";
import { Toast } from "../ui/Toast";
import { CanvasMenu } from "./CanvasMenu";
import { archiveCanvas, createCanvas, duplicateCanvas, listCanvases, pinCanvas, renameCanvas, thumbnailUrl } from "./homeApi.ts";
import { canvasMeta, homeSections, newCanvasTitle, offerLabel, type CanvasSummary } from "./homeLogic.ts";
import { MoreIcon, PinIcon, PlusIcon, SearchIcon } from "./icons";
import "./Home.css";

const f: typeof fetch = (input, init) => fetch(input, init);
const href = (c: CanvasSummary) => `/?canvas=${encodeURIComponent(c.id)}`;

type Toasted = { message: string; actionLabel?: string; onAction?: () => void };

function Thumb({ canvas, className }: { canvas: CanvasSummary; className: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={className}>
      {!failed && <img src={thumbnailUrl(canvas)} alt="" loading="lazy" onError={() => setFailed(true)} />}
    </span>
  );
}

function Offers({ n }: { n: number }) {
  return n > 0 ? <Badge>{offerLabel(n)}</Badge> : null;
}

/** One canvas as a link plus its actions button. variant: the big Continue card, a Recent row or a grid tile. */
function Item(props: {
  canvas: CanvasSummary;
  variant: "feature" | "row" | "tile";
  now: Date;
  menuOpen: boolean;
  openMenu: () => void;
  menu: React.ReactNode;
}) {
  const { canvas: c, variant, now } = props;
  const pin = c.pinned && <span className="ink-home-pin" role="img" aria-label="Pinned"><PinIcon /></span>;
  return (
    <div
      className={`ink-home-item ink-home-item--${variant}`}
      onContextMenu={(e) => {
        e.preventDefault(); // long press on the tablet
        props.openMenu();
      }}
    >
      <a href={href(c)} onClick={onLinkClick} className="ink-home-link-item">
        <Thumb canvas={c} className="ink-home-thumb" />
        {variant === "feature" && (
          <>
            <span className="ink-home-feature__offers"><Offers n={c.open_offers} /></span>
            <span className="ink-home-caption">
              <span className="ink-home-title">{pin}{c.title}</span>
              <span className="ink-home-meta">{canvasMeta(c, now)}</span>
            </span>
          </>
        )}
        {variant === "row" && (
          <>
            <span className="ink-home-text">
              <span className="ink-home-title">{pin}{c.title}</span>
              <span className="ink-home-meta">{canvasMeta(c, now)}</span>
            </span>
            <Offers n={c.open_offers} />
          </>
        )}
        {variant === "tile" && (
          <>
            <span className="ink-home-title">{pin}{c.title}</span>
            <span className="ink-home-tile__offers"><Offers n={c.open_offers} /></span>
          </>
        )}
      </a>
      <IconButton label={`More actions for ${c.title}`} className="ink-home-more" aria-expanded={props.menuOpen} onClick={props.openMenu}>
        <MoreIcon />
      </IconButton>
      {props.menuOpen && props.menu}
    </div>
  );
}

export function Home() {
  const [canvases, setCanvases] = useState<CanvasSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [archivedView, setArchivedView] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [toast, setToast] = useState<Toasted | null>(null);
  const [now, setNow] = useState(() => new Date());

  const load = useCallback(async () => {
    try {
      setCanvases(await listCanvases(f, archivedView ? "true" : "false"));
      setNow(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load canvases");
    }
  }, [archivedView]);
  useEffect(() => {
    void load();
  }, [load]);
  const showArchived = (on: boolean) => {
    setCanvases(null); // the other list is not the one on screen
    setMenuFor(null);
    setArchivedView(on);
  };

  const closeMenu = useCallback(() => setMenuFor(null), []);
  const dismissToast = useCallback(() => setToast(null), []);

  /** Run a change; on success refetch, on failure say why. */
  const change = async (fn: () => Promise<unknown>, after?: () => Toasted) => {
    try {
      await fn();
      if (after) setToast(after());
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "That did not work" });
    }
    await load();
  };

  const create = async () => {
    try {
      const made = await createCanvas(f, newCanvasTitle(new Date()));
      navigate(`/?canvas=${encodeURIComponent(made.id)}`);
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "Could not create a canvas" });
    }
  };

  const menuFrom = (c: CanvasSummary) => (
    <CanvasMenu
      canvas={c}
      onClose={closeMenu}
      actions={{
        rename: (title) => void change(() => renameCanvas(f, c.id, title)),
        pin: () => void change(() => pinCanvas(f, c.id, !c.pinned)),
        duplicate: () => void change(() => duplicateCanvas(f, c.id)),
        archive: () =>
          void change(
            () => archiveCanvas(f, c.id, !c.archived),
            () =>
              c.archived
                ? { message: `Restored ${c.title}` }
                : {
                    message: `Archived ${c.title}`,
                    actionLabel: "Undo",
                    onAction: () => {
                      setToast(null);
                      void change(() => archiveCanvas(f, c.id, false));
                    },
                  },
          ),
      }}
    />
  );
  const item = (c: CanvasSummary, variant: "feature" | "row" | "tile") => (
    <Item key={c.id} canvas={c} variant={variant} now={now} menuOpen={menuFor === c.id} openMenu={() => setMenuFor(c.id)} menu={menuFrom(c)} />
  );

  const sections = useMemo(() => homeSections(canvases ?? [], archivedView ? "" : query, now), [canvases, query, now, archivedView]);
  const searching = query.trim() !== "";

  let body: React.ReactNode;
  if (error && !canvases) {
    body = (
      <p className="ink-home-state" role="alert">
        {error}
        <Button variant="secondary" onClick={() => void load()}>Retry</Button>
      </p>
    );
  } else if (!canvases) {
    body = <p className="ink-home-state">Loading</p>;
  } else if (archivedView) {
    body = (
      <section className="ink-home-section">
        <div className="ink-home-sectionhead">
          <h1 className="ink-home-h">Archived</h1>
          <span className="ink-home-count">{canvases.length}</span>
          <span className="ink-home-spacer" />
          <button type="button" className="ink-home-textlink" onClick={() => showArchived(false)}>Back to canvases</button>
        </div>
        {canvases.length === 0 ? <p className="ink-home-state">Nothing archived.</p> : <div className="ink-home-grid">{sections.all.map((c) => item(c, "tile"))}</div>}
      </section>
    );
  } else if (canvases.length === 0) {
    body = (
      <p className="ink-home-state">
        Welcome. Start a canvas and write on it; Claude can read it and draw back.
        <Button variant="primary" onClick={() => void create()}><PlusIcon />New canvas</Button>
      </p>
    );
  } else {
    body = (
      <>
        {!searching && sections.continue && (
          <div className="ink-home-main">
            <section>
              <h1 className="ink-home-h">Continue</h1>
              {item(sections.continue, "feature")}
            </section>
            <section>
              <h2 className="ink-home-h">Recent</h2>
              {sections.recent.map((c) => item(c, "row"))}
            </section>
          </div>
        )}
        <section className="ink-home-section">
          <div className="ink-home-sectionhead">
            <h2 className="ink-home-h">{searching ? "Matching canvases" : "All canvases"}</h2>
            <span className="ink-home-count">{sections.all.length}</span>
            <span className="ink-home-spacer" />
            <button type="button" className="ink-home-textlink" onClick={() => showArchived(true)}>Archived</button>
          </div>
          {sections.all.length === 0 ? <p className="ink-home-state">No canvas matches.</p> : <div className="ink-home-grid">{sections.all.map((c) => item(c, "tile"))}</div>}
        </section>
      </>
    );
  }

  return (
    <div className="ink-home">
      <header className="ink-home-header">
        <p className="ink-home-wordmark">Inkbridge</p>
        <label className="ink-home-search">
          <SearchIcon />
          <span className="ink-home-sr">Search canvases and ink</span>
          <input type="search" placeholder="Search your canvases and ink" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <span className="ink-home-spacer" />
        <Button variant="primary" className="ink-home-new" onClick={() => void create()}>
          <PlusIcon />
          New canvas
        </Button>
      </header>
      <main className="ink-home-body">{body}</main>
      {toast && (
        <div className="ink-home-toast">
          <Toast message={toast.message} actionLabel={toast.actionLabel} onAction={toast.onAction} onDismiss={dismissToast} />
        </div>
      )}
    </div>
  );
}
