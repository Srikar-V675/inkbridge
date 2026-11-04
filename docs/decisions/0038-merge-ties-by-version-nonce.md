# 0038 Conflict merge breaks version ties by versionNonce (INK-090)

**Problem.** Both tabs start from stored version v and each edit bumps the element to v+1, so a concurrent edit of the same element is a tie. `mergeScenes` gave ties to the server copy, so a delete, move or resize made in the losing tab vanished. Nothing sent it either, because the delta save skips elements whose version equals the baseline. The only trace was the localStorage backup, which nothing reads.

**Decision.** On a tie the lower `versionNonce` wins, the same rule Excalidraw's own reconcile uses, so whichever tab saves first, both converge on one element. An equal nonce keeps the server copy. The conflict notice counts the local edits the other tab replaced, and the backup is still kept.

**Why a won tie must be resent.** Two traps would otherwise drop a tie win after the rule is correct:
- `resolveConflict` only saves when the merged signature (`id:version`) differs from the last confirmed one. A tie win has the same signature as the server scene, so nothing was scheduled. It now saves when any element was kept.
- `deltaFor` skips elements whose version equals the baseline, and after the reload the baseline holds the server version. The kept ids are set to `-1` in the baseline so the next delta includes them.

**Undo caveat (not verified against a real run).** The tie rule assumes Excalidraw's undo and edits always bump `version` and never reuse an older number. If undo ever reused one, `deltaFor` would skip that element. The library cannot be unit-tested in Node here, so this stays a documented assumption.

**Not done.** The localStorage backup is still never read back. A tie resolved by nonce can overwrite a server edit that was saved later; this is intended for symmetry, and the loser survives only in the backup. Elements with no `versionNonce` fall back to 0, so their ties still go to the server, as before.
