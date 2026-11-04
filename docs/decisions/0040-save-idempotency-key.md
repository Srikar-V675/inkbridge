# 0040 Idempotent scene saves (INK-083)

**Problem.** A user saw "another tab saved first" with one tab open. Likely cause: a PUT timed out or lost its response after the server had committed it; the client retried with the old `base_version` and got a 409 from its own save. Delta saves (0036) do not change this.

**Decision.** Every scene PUT carries `X-Inkbridge-Save: <tabId>:<seq>`. The server remembers `(document, key) -> version produced` (in memory, 256 entries, oldest dropped). A repeat of a key returns that version with 200 and applies nothing; the check runs inside the write lock, before the version compare. A rolled-back save records nothing. A replay re-publishes `chunks.updated` (harmless).

**Identical-body rule.** The client keeps the built request (`unsettled`) after a network error or timeout and resends the same key and the same body; it clears it on any HTTP answer (ok, 409, 4xx, 5xx) and on `load()`. Otherwise a retry carrying newer edits would be swallowed as a replay. Newer edits go in the following PUT with a new key (one extra save). While a PUT is in flight no second one is sent (`saving`). Requests time out after 30 s (`AbortSignal.timeout`).

**Limit.** The key store is lost on a server restart, so a retry straddling a restart can still 409 once. Upgrade to a table if that is ever seen.

**Diagnosis.** Every scene PUT logs tab id, client IP, user agent and key on `inkbridge.request`. The API remembers the last keyed writer per document; a 409 body gains `detail.last_writer = {tab, same_ip}` and the notice says "Another device saved first" when `same_ip` is false, otherwise "Another tab". Behind the Vite dev proxy the IP is the proxy's, so `same_ip` is true for all dev traffic; the tab id in the log is the reliable discriminator (a different tab id on the same IP is a second tab or browser; the same tab id with a 409 would be a bug). Acceptance criterion 1 (the real cause) is confirmed from these logs after deploy.

**Follow-up.** INK-063 (refetch on focus) would remove the genuine other-device conflicts; not implemented here.
