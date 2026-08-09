import Markdown, { type Components } from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import './MessageContent.css';

/**
 * One message body, rendered for the panel it sits in.
 *
 * The composer writes Markdown — that is the whole convention, there is no
 * structured formatting field — and this turns it back into elements. GFM is the
 * dialect because tables, strikethrough and autolinks are what a model actually
 * reaches for, and none of them are core Markdown.
 *
 * **Assistant only.** A user message is echoed input, not model output: rendering
 * it would let anyone type `**` and produce a bubble that formats like an answer.
 * It stays literal, with its newlines preserved.
 *
 * **No raw HTML.** react-markdown builds React elements directly rather than
 * setting innerHTML, so without `rehype-raw` there is no injection surface and
 * nothing to sanitise. Do not add `rehype-raw` here without also adding
 * `rehype-sanitize` — the model's output is untrusted text.
 */

/** Schemes a model may link to. Anything else renders as text, not a link. */
const SAFE_LINK = /^(https?:|mailto:)/i;

/**
 * Headings collapse to bold.
 *
 * The panel is one `var(--chat-width)` column of 13.5px text. An `h1` sized in
 * proportion to that body would either dwarf the bubble or be indistinguishable
 * from it, and the model has no idea how wide its output lands. Keeping the
 * emphasis but dropping the scale is the honest reading of a heading here.
 */
function headingAsBold({ children }: { children?: React.ReactNode }) {
  return (
    <p className="md-heading">
      <strong>{children}</strong>
    </p>
  );
}

const COMPONENTS: Components = {
  h1: headingAsBold,
  h2: headingAsBold,
  h3: headingAsBold,
  h4: headingAsBold,
  h5: headingAsBold,
  h6: headingAsBold,

  a({ href, children }) {
    if (!href || !SAFE_LINK.test(href)) return <>{children}</>;
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },

  // A table is the one thing here wider than the column it renders into, so it
  // scrolls inside its own box rather than forcing the panel to.
  table({ children }) {
    return (
      <div className="md-table-wrap">
        <table>{children}</table>
      </div>
    );
  },

  // Never fetched: a remote image on a URL the model chose is a tracking pixel
  // with extra steps. The alt text is kept rather than dropping the node, which
  // would leave an empty paragraph where the model wrote a caption.
  img({ alt }) {
    return <>{alt}</>;
  },
};

interface MessageContentProps {
  content: string;
  role: 'user' | 'assistant';
}

export function MessageContent({ content, role }: MessageContentProps) {
  if (role === 'user') return <p className="md-plain">{content}</p>;

  return (
    <div className="md-body">
      <Markdown
        // remarkBreaks because a model uses a single newline to mean a line
        // break; GFM alone folds those into the paragraph and the answer runs on.
        remarkPlugins={[remarkGfm, remarkBreaks]}
        components={COMPONENTS}
      >
        {content}
      </Markdown>
    </div>
  );
}
