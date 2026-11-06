import type { ReactNode } from "react";
import { onLinkClick } from "../lib/nav";
import { Button } from "../ui/Button";
import { AskIcon, BackIcon } from "./icons";

export function TopBar(props: { title: string; status: ReactNode; chunks?: ReactNode; onAsk: () => void; askOpen: boolean }) {
  return (
    <header className="ink-topbar">
      <a href="/" onClick={onLinkClick} className="ink-button ink-button--quiet ink-topbar__back">
        <BackIcon />
        Canvases
      </a>
      <h1 className="ink-topbar__title">{props.title}</h1>
      <span className="ink-topbar__status">{props.status}</span>
      <span className="ink-topbar__spacer" />
      {props.chunks}
      <Button variant="primary" aria-pressed={props.askOpen} onClick={props.onAsk}>
        <AskIcon />
        Ask
      </Button>
    </header>
  );
}
