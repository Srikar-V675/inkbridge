export interface Token { name: string; value: string }

/** Declarations of a generated tokens.css, in file order. */
export function parseTokenCss(css: string): Token[] {
  return [...css.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => ({ name: m[1], value: m[2].trim() }));
}

/** Follow `var(--x)` chains to a literal; unknown variable returns the input. */
export function resolveVar(tokens: Token[], value: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(value.trim());
  if (!m) return value.trim();
  const hit = tokens.find((t) => t.name === m[1]);
  return hit ? resolveVar(tokens, hit.value) : value;
}
