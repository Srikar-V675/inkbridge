# 0036 Delta scene saves (INK-075)

**Problem.** Every autosave PUT the whole scene. A canvas of 496 elements and 12k points is 1.05 MB, and from the tablet through the Vite proxy one save took 96 s while the server needed 41 ms (request 173 ms when sent locally). The cost grew with the page, not with the edit.

**Decision.** `PUT /documents/{id}/scene` accepts `delta: true`: `elements` holds only the elements changed since `base_version`. The server replaces stored elements by id in place and appends new ones, inside the same write lock and version check as a full save. The client keeps `id -> version` of the last server-confirmed scene (load, successful save) and sends the elements whose version differs.

**Why it is safe.** `base_version` pins the stored scene to what the client diffed against; any other writer bumps the version, the save gets a 409, and the conflict path reloads and rebuilds the baseline. A failed save keeps the old baseline, so the retry carries the whole unconfirmed diff. Deleted ink stays in the scene as `isDeleted`, so a delta never has to remove anything. If an element the server holds is missing from the client list, or a delta would not be smaller, the client sends a full save. The merged scene is still capped at 50,000 elements (422).

**Not done.** gzip of the request body (a delta is a few KB, so it buys little); serving the built web from the API to drop the Vite proxy from the path (INK-074).
