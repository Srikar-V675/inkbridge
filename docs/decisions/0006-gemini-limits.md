# 0006: Gemini recognizer and its limits

Status: accepted (INK-013); live check **not run**

- `inkbridge.recognizer.recognize(png, hint)` returns `Recognition(text, latex, kind, model)`. `GeminiRecognizer`
  is the default implementation; the worker (INK-014) and tests accept any callable matching the `Recognizer`
  protocol, so the model is swappable and CI never touches the network.
- Default model `gemini-2.5-flash-lite` (override with `GEMINI_MODEL`); key from `GEMINI_API_KEY`. The key is
  read from the environment only, never logged: error messages from the transport are redacted and `repr`
  omits it.
- Errors are typed (`RateLimited`, `RecognizerTimeout`, `BadResponse`, `MissingApiKey`). 429 is retried with
  exponential backoff (2 s, 4 s, 8 s, 3 retries); timeouts and bad replies are raised for the worker to
  schedule. Calls are serialised and spaced by 4 s (about 15 requests/minute) to stay inside free-tier limits.
- The reply is requested as JSON (`text`, `latex`, `kind`); code fences are tolerated; an unknown `kind`
  becomes `mixed`.
- Privacy: the free tier may train on content. Only test and eval pages go through this path.
- **Live check not run.** No `GEMINI_API_KEY` was available when this was built. Model id, rate limits (the
  4 s spacing is an assumption) and maximum image size are unverified. To close this: set the key, run
  `recognize()` on one handwritten test page, and record the observed limits here.
