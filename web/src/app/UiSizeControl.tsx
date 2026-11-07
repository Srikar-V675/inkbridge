import { useSyncExternalStore } from "react";
import { Button } from "../ui/Button";
import { nextSize, sizeLabel, sizeShort } from "./uiScale";
import { uiScale } from "./uiScaleStore";

// Top-bar "Size S/M/L": cycles the UI size of the shell chrome (INK-177, decision 0083).
export function UiSizeControl() {
  const scale = useSyncExternalStore(uiScale.subscribe, uiScale.get);
  return (
    <Button
      variant="quiet"
      onClick={() => uiScale.cycle()}
      aria-label={`UI size ${sizeLabel(scale)}. Tap for ${sizeLabel(nextSize(scale))}.`}
      title="Interface size (Small, Medium, Large)"
    >
      Size {sizeShort(scale)}
    </Button>
  );
}
