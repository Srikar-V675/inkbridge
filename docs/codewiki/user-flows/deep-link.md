# Deep link from a note to a chunk

**Story:** as a reader of a vault note, I want to click a block and land on the exact ink it came from.

1. Each block carries `?canvas=<id>&chunk=<id>` on `INKBRIDGE_PUBLIC_URL`.
2. `route.ts` reads both params; the app loads the scene, then `chunks.ts` pans and highlights the chunk. A toggleable overlay (`ChunkOverlay.tsx`) shows chunk boxes (decision 0014).
3. If the chunk was replaced, the successor id applies (decision 0011).

Plain URLs only: no Obsidian plugin exists and none is planned.
