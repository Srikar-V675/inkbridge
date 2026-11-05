// Safe renderer for untrusted answer_md (INK-049, docs/decisions/0046). Plain .ts so Node tests import it.
import { createElement as h } from "react";
import Markdown from "react-markdown";

const SAFE = /^(https?:|mailto:)/i;
export const safeHref = (u: string) => (SAFE.test(u.trim()) ? u : "");

export function AnswerMarkdown({ source }: { source: string }) {
  return h(
    Markdown,
    {
      skipHtml: true,
      urlTransform: safeHref,
      components: {
        a: ({ href, children }) =>
          href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, children) : h("span", null, children),
        img: ({ alt }) => h("span", null, alt ? `[image: ${alt}]` : "[image]"), // remote images blocked
      },
    },
    source,
  );
}
