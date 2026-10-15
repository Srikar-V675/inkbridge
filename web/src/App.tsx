// Day-1 spike: throwaway page that runs the five feasibility checks from docs/project-doc.html §11.
import { useEffect, useState } from "react";
import {
  Excalidraw,
  convertToExcalidrawElements,
  exportToBlob,
  restoreElements,
  serializeAsJSON,
} from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import { parseMermaidToExcalidraw } from "@excalidraw/mermaid-to-excalidraw";

const KEY = "inkbridge-spike-scene";
const MERMAID = "flowchart LR\n  A[Region] --> B[Gemini]\n  B --> C[Agent]";

export default function App() {
  const [api, setApi] = useState<any>(null);
  const [log, setLog] = useState<string[]>([]);
  const [png, setPng] = useState<string | null>(null);
  const say = (s: string) => {
    setLog((l) => [s, ...l].slice(0, 40));
    fetch("/__log", { method: "POST", body: s }).catch(() => {});
  };

  // Check 1: secure context + what the stylus reports.
  useEffect(() => {
    say(`secure context: ${window.isSecureContext} | origin: ${location.origin}`);
    const onDown = (e: PointerEvent) =>
      say(`pointerdown type=${e.pointerType} pressure=${e.pressure.toFixed(2)}`);
    window.addEventListener("pointerdown", onDown);
    return () => window.removeEventListener("pointerdown", onDown);
  }, []);

  const selected = () => {
    const ids = api.getAppState().selectedElementIds;
    return api.getSceneElements().filter((e: any) => ids[e.id]);
  };

  // Check 2: read selection, incl. freedraw pressures.
  const check2 = () => {
    const sel = selected();
    if (!sel.length) return say("select something first");
    sel.forEach((e: any) =>
      say(`${e.type} ${e.id.slice(0, 6)} points=${e.points?.length ?? "-"} pressures=${
        e.pressures ? `${e.pressures.length} (simulate=${e.simulatePressure})` : "none"
      }`),
    );
  };

  // Check 3: add a text element and a Mermaid flowchart.
  const check3 = async () => {
    try {
      const text = convertToExcalidrawElements([
        { type: "text", x: 0, y: 0, text: "agent draft", strokeStyle: "dashed" } as any,
      ]);
      const { elements, files } = await parseMermaidToExcalidraw(MERMAID);
      const flow = convertToExcalidrawElements(elements as any).map((e: any) => ({
        ...e,
        x: e.x + 40,
        y: e.y + 120,
      }));
      if (files) api.addFiles(Object.values(files));
      api.updateScene({ elements: [...api.getSceneElements(), ...text, ...flow] });
      say(`added ${text.length} text + ${flow.length} mermaid elements`);
    } catch (err) {
      say(`check3 failed: ${err}`);
    }
  };

  // Check 4: tag selection with customData, save, then reload the page and read it back.
  const check4Save = () => {
    const ids = api.getAppState().selectedElementIds;
    const els = api
      .getSceneElements()
      .map((e: any) => (ids[e.id] ? { ...e, customData: { author: "agent", draft: true } } : e));
    api.updateScene({ elements: els });
    localStorage.setItem(KEY, serializeAsJSON(els, api.getAppState(), api.getFiles(), "local"));
    say("saved with customData; now reload the page and press 'Read customData'");
  };
  const check4Read = () => {
    const raw = localStorage.getItem(KEY);
    if (!raw) return say("nothing saved");
    const els = restoreElements(JSON.parse(raw).elements, null);
    api.updateScene({ elements: els });
    const tagged = els.filter((e: any) => e.customData);
    say(`restored ${els.length} elements, ${tagged.length} with customData: ${JSON.stringify(tagged[0]?.customData)}`);
  };

  // Check 5: export only the selection as PNG.
  const check5 = async () => {
    const sel = selected();
    if (!sel.length) return say("select something first");
    const blob = await exportToBlob({
      elements: sel,
      appState: { ...api.getAppState(), exportBackground: true },
      files: api.getFiles(),
      mimeType: "image/png",
    });
    setPng(URL.createObjectURL(blob));
    say(`exported selection PNG: ${(blob.size / 1024).toFixed(1)} KB`);
  };

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr auto", height: "100vh" }}>
      <div style={{ display: "flex", gap: 8, padding: 8, flexWrap: "wrap" }}>
        <button onClick={check2} disabled={!api}>2 Read selection</button>
        <button onClick={check3} disabled={!api}>3 Add text + Mermaid</button>
        <button onClick={check4Save} disabled={!api}>4 Tag + save</button>
        <button onClick={check4Read} disabled={!api}>4 Read customData</button>
        <button onClick={check5} disabled={!api}>5 Export selection PNG</button>
      </div>
      <div style={{ minHeight: 0 }}>
        <Excalidraw excalidrawAPI={setApi} />
      </div>
      <div style={{ display: "flex", gap: 12, padding: 8, maxHeight: "25vh", overflow: "auto", font: "12px monospace" }}>
        <div style={{ flex: 1 }}>{log.map((l, i) => <div key={i}>{l}</div>)}</div>
        {png && <img src={png} alt="selection export" style={{ maxHeight: 120, border: "1px solid #999" }} />}
      </div>
    </div>
  );
}
