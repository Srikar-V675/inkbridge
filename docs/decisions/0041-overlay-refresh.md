# 0041: Chunk overlay refreshes on one coalesced signal

Status: accepted (INK-079). Builds on 0014 (overlay) and 0017 (recognition worker).
Code: `web/src/chunkRefresh.ts` (`createRefresh`, `onVisible`), `web/src/ChunkOverlay.tsx`
(`useChunks`), `web/src/App.tsx` (wiring), `web/tests/chunkRefresh.test.ts`.

- **Problem.** The overlay refetched its chunk list only when a save finished. A chunk push
  (`chunks.updated`) from another client, a socket reconnect, or the tablet waking from sleep left
  the boxes stale until the next save or a reload. A push lost while asleep is gone for good, so
  the list must be fetched again on those events.
- **One signal, four sources.** Save finishing, `chunks.updated`, socket connect and
  `visibilitychange` to visible all call `refresh.fire()`. The overlay subscribes once per
  "Show chunks" session. The initial load on turning the overlay on stays immediate.
- **Coalesced.** A burst of fires becomes one listener call after 800 ms (trailing timer, no
  leading call). A save that pushes and then reconnects costs one fetch, not three.
- **Fetch when idle.** The listener calls the fetch through `requestIdleCallback` with a 2000 ms
  timeout (`setTimeout(0)` where it is missing), so a refetch never runs during a pen stroke. The
  timeout bounds the wait. Worst case from a change to boxes on screen is about 2.8 s; typical is
  about 1 s.
- **Stale responses still lose.** The existing `latest` counter keeps an out-of-order response from
  overwriting a newer list.
- **Reconnect needs no other work.** `OpsSocket.onConnection(true)` fires on every connect, the
  first one included (harmless: no subscribers while the overlay is off). Drafts and delivered ops
  are replayed by the server on connect already, so they are not touched here.
- **Not done.** No backoff on the list fetch itself and no cap on a very large list (cap 500 on the
  server). A mega-chunk list is fetched whole each time; coalescing is the only mitigation.
