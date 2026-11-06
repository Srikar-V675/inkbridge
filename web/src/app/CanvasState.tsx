import { backTo, onLinkClick } from "../lib/nav";

/** What the canvas area says when the scene did not open (INK-172): no such canvas, or a failed load. */
export function CanvasState({ kind, canvas }: { kind: "missing" | "error"; canvas: string }) {
  return (
    <div className="ink-shell__state">
      {kind === "missing" ? (
        <>
          <h2 className="ink-shell__state-title">Canvas not found</h2>
          <p>
            No canvas has the id <code>{canvas}</code>.
          </p>
        </>
      ) : (
        <>
          <h2 className="ink-shell__state-title">Could not open this canvas</h2>
          <p>Check the connection and try again.</p>
        </>
      )}
      <a className="ink-button ink-button--secondary" href="/" onClick={(e) => onLinkClick(e, backTo)}>
        Back to canvases
      </a>
    </div>
  );
}
