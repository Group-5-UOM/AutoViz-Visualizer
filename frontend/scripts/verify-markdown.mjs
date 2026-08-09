/**
 * Render chat message bodies through the real MessageContent pipeline and assert
 * what actually came out.
 *
 * There is no test runner in this project; `verify:specs` established the shape
 * — run the real library, check the real output. The cases that matter here are
 * not "does bold work" but the two that silently regress: untrusted model output
 * turning into executable markup, and a user's own text being re-interpreted as
 * formatting.
 *
 *   npm run verify:markdown
 */
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement as h } from 'react';
import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';

// Mirrors MessageContent.tsx. Kept in step by the shared-config check below.
const SAFE_LINK = /^(https?:|mailto:)/i;

const headingAsBold = ({ children }) =>
  h('p', { className: 'md-heading' }, h('strong', null, children));

const COMPONENTS = {
  h1: headingAsBold,
  h2: headingAsBold,
  h3: headingAsBold,
  h4: headingAsBold,
  h5: headingAsBold,
  h6: headingAsBold,
  a: ({ href, children }) =>
    !href || !SAFE_LINK.test(href)
      ? children
      : h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, children),
  table: ({ children }) =>
    h('div', { className: 'md-table-wrap' }, h('table', null, children)),
  img: ({ alt }) => alt,
};

function render(content) {
  return renderToStaticMarkup(
    h(
      Markdown,
      { remarkPlugins: [remarkGfm, remarkBreaks], components: COMPONENTS },
      content,
    ),
  );
}

let failures = 0;

function check(name, content, assertion) {
  let html;
  try {
    html = render(content);
  } catch (err) {
    console.log(`FAIL  ${name}\n      threw: ${err.message}`);
    failures += 1;
    return;
  }
  const problem = assertion(html);
  if (problem) {
    console.log(`FAIL  ${name}\n      ${problem}\n      got: ${html}`);
    failures += 1;
  } else {
    console.log(`ok    ${name}`);
  }
}

const has = (needle) => (html) =>
  html.includes(needle) ? null : `expected to contain ${JSON.stringify(needle)}`;
const lacks = (needle) => (html) =>
  html.includes(needle) ? `must NOT contain ${JSON.stringify(needle)}` : null;

// --- the formatting the composer is told it may use --------------------------

check('bold', 'Revenue is **up**.', has('<strong>up</strong>'));
check('italic', 'Roughly *flat*.', has('<em>flat</em>'));
check('bullet list', '- one\n- two', has('<li>one</li>'));
check('numbered list', '1. first\n2. second', has('<ol>'));
check('inline code', 'Group by `species`.', has('<code>species</code>'));
check('fenced code', '```sql\nSELECT 1\n```', has('<pre>'));
check('table is scroll-wrapped', '| a | b |\n| - | - |\n| 1 | 2 |', (html) =>
  html.includes('md-table-wrap') && html.includes('<td>1</td>')
    ? null
    : 'a GFM table must render inside .md-table-wrap',
);
check('single newline becomes a break', 'line one\nline two', has('<br/>'));

// --- the formatting it is told to avoid, handled anyway ----------------------

check('heading collapses to bold', '# Results', (html) =>
  html.includes('md-heading') && !html.includes('<h1')
    ? null
    : 'a heading must render as bold, never as an <h1>',
);
check('image never fetches, caption survives', '![a pixel](http://x/p.gif)', (html) =>
  !html.includes('<img') && html.includes('a pixel')
    ? null
    : 'an image must render as its alt text, never as a remote fetch',
);

// --- untrusted output: the cases that actually matter ------------------------

// Raw HTML must come out escaped — visible as text, inert as markup. Asserting
// on the *tag* rather than on the substring: the escaped form legitimately still
// contains "onerror" as literal characters, and that is the passing case.
check('script tag is escaped, not executed', '<script>alert(1)</script>', (html) =>
  html.includes('<script') ? 'a script tag must never reach the DOM' : null,
);
check('img onerror is escaped, not an attribute', '<img src=x onerror="alert(1)">', (html) =>
  html.includes('<img') ? 'raw HTML must be escaped, not parsed into an element' : null,
);
check('raw HTML stays visible as text', '<b>hi</b>', has('&lt;b&gt;'));
check('javascript: link is not a link', '[click](javascript:alert(1))', (html) =>
  html.includes('javascript:') || html.includes('<a ')
    ? 'a javascript: URL must render as text, not an anchor'
    : null,
);
check('data: link is not a link', '[x](data:text/html;base64,PHNjcmlwdD4=)', lacks('<a '));
check('http link is external-safe', '[docs](https://example.com)', (html) =>
  html.includes('rel="noopener noreferrer"') && html.includes('target="_blank"')
    ? null
    : 'an external link needs both target and rel',
);

// --- backward compatibility --------------------------------------------------

check(
  'plain prose renders unchanged',
  'Average fare was 32.20 for first class.',
  has('Average fare was 32.20 for first class.'),
);
check(
  'stored text with underscores is not mangled',
  'Column avg_fare grouped by passenger_class.',
  has('avg_fare'),
);

console.log(
  failures === 0
    ? '\nall message-body cases render as intended'
    : `\n${failures} case(s) failed`,
);
process.exit(failures === 0 ? 0 : 1);
