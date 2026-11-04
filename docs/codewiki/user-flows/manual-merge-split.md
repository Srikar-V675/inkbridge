# Manual chunk merge and split

**Story:** as a note-taker, I want to fix a wrongly grouped chunk by merging or splitting it by hand.

1. Toggle "Show chunks". Tap one or more chunk label chips (big tap targets) to select their ink, or lasso part of a chunk with Excalidraw's selection. Selected chunks get an orange border (dashed if only part is selected).
2. Merge or Split buttons (`web/src/overrides.ts`) call `POST /documents/{id}/chunks/merge` or `/split`.
3. The result is a **pinned** chunk (`regions.pinned=1`); the chunker leaves it alone on later saves, and the old chunks become orphans with `successor_of`.
4. `check_sync` reports `replaced`, so notes migrate on the next export.

Decision 0024. Fourth-from-last on the cut list (fallback: tune `k`).
