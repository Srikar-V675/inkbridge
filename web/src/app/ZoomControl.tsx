import { useSyncExternalStore } from "react";
import { IconButton } from "../ui/IconButton";
import { ZoomInIcon, ZoomOutIcon } from "./icons";
import type { RailStore } from "./ToolRail";

export function ZoomControl({ store }: { store: RailStore }) {
  const { zoom } = useSyncExternalStore(store.subscribe, store.get);
  return (
    <div className="ink-zoom">
      <IconButton label="Zoom out" onClick={() => store.zoomBy(-1)}>
        <ZoomOutIcon />
      </IconButton>
      <span className="ink-zoom__value">{Math.round(zoom * 100)}%</span>
      <IconButton label="Zoom in" onClick={() => store.zoomBy(1)}>
        <ZoomInIcon />
      </IconButton>
    </div>
  );
}
