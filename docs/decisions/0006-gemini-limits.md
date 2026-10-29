# 0006: Gemini recognizer and its limits

Status: accepted (INK-013); live check run on synthetic pages

- A recognizer is a callable `(png, hint) -> Recognition(text, latex, kind, model)` (the module-level `recognize()` helper was
  removed in INK-014, decision 0017: the opt-in worker is the only path to the model). `GeminiRecognizer`
  is the default implementation; the worker (INK-014) and tests accept any callable matching the `Recognizer`
  protocol, so the model is swappable and CI never touches the network.
- Default model `gemini-3.5-flash-lite` (override with `GEMINI_MODEL`); key from `GEMINI_API_KEY`. The key is
  read from the environment only, never logged: error messages from the transport are redacted and `repr`
  omits it.
- Errors are typed (`RateLimited`, `RecognizerTimeout`, `BadResponse`, `MissingApiKey`, `InvalidApiKey`).
  `MissingApiKey` and `InvalidApiKey` (401/403, or 400 "API key not valid") derive from `PermanentError`: the
  worker stops on them instead of retrying. HTTP 408/504 map to `RecognizerTimeout`. 429 is retried with
  exponential backoff (2 s, 4 s, 8 s, 3 retries); timeouts and bad replies are raised for the worker to
  schedule. Calls are serialised and spaced by 4 s (about 15 requests/minute) to stay inside free-tier limits.
- The reply is requested as JSON (`text`, `latex`, `kind`); code fences are tolerated; `kind` is matched
  case-insensitively and an unknown or non-string `kind` becomes `mixed`. Any reply that is not that shape
  raises `BadResponse`, never another exception type.
- Privacy: the free tier may train on content. Only test and eval pages go through this path.
## Live check (23-25 Oct 2026, synthetic printed-text pages only)
- `gemini-2.5-flash-lite` returns **404** ("no longer available to new users"). The default is now the pinned
  `gemini-3.5-flash-lite` (also listed for the key: `gemini-3.1-flash-lite`, `gemini-flash-lite-latest`).
  A 404 is raised as a plain `RecognizerError` with the API message, so a retired model is visible.
- A 600x200 PNG (6 KB), 3000x1500 (38 KB) and 8000x6000 (193 KB) all returned the correct text in 2-9 s
  (larger images are slower). No size limit was hit up to 8000x6000; PNGs above that were not tried.
- The model sometimes wraps its JSON in a list and answers `kind: "text"`. The parser unwraps lists (joining
  lines) and maps `text` -> `handwriting`, `math` -> `equation`.
- 20 back-to-back calls with spacing and retries disabled all succeeded at about 5 s each (roughly 12 requests
  a minute); no 429 appeared at that rate. The free-tier ceiling was not found, so the 4 s spacing stays a safe
  default, not a measured limit.
- Still unverified: handwriting accuracy (the test pages were printed text); that is what E1 measures.
