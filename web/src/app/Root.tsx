import { useEffect } from "react";
import { Home } from "../home/Home";
import { canvasKey } from "../lib/route";
import App from "./App";
import { useLocation } from "./useLocation";

/** Home or one canvas. A canvas view is remounted per canvas (and per chunk link), so Excalidraw and sync start clean. */
export default function Root() {
  const loc = useLocation();
  const opened = loc.kind === "canvas" ? loc.canvas : null;
  useEffect(() => {
    // Stamps "last opened" for the Continue card; a failure only costs that.
    if (opened) void fetch(`/documents/${encodeURIComponent(opened)}/open`, { method: "POST" }).catch(() => {});
  }, [opened]);
  return loc.kind === "home" ? <Home /> : <App key={canvasKey(loc)} route={loc} />;
}
