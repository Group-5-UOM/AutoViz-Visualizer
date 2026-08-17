/**
 * Setup snippets for connecting an MCP host to AutoViz.
 *
 * Separated from the Connections panel because these are **contracts with other
 * people's software**, not presentation. Claude Desktop and Gemini CLI each read
 * a differently-shaped config file, and a wrong key name fails the way an
 * integration always fails: silently, with the server never contacted and
 * nothing in any log to say why. That is worth a test, and a test needs this
 * out of a `.tsx` file that imports CSS.
 */

export interface McpSnippet {
  id: string;
  label: string;
  /** Where this goes, because pasting it in the wrong place is the usual failure. */
  hint: string;
  build: (url: string) => string;
}

export const MCP_SNIPPETS: McpSnippet[] = [
  {
    id: 'url',
    label: 'Paste the URL',
    hint: 'Gemini → Connected Apps → Custom apps for Spark, and most hosted UIs.',
    build: (url) => url,
  },
  {
    id: 'claude',
    label: 'Claude Desktop',
    hint: 'claude_desktop_config.json — restart Claude after saving.',
    build: (url) =>
      JSON.stringify({ mcpServers: { autoviz: { type: 'http', url } } }, null, 2),
  },
  {
    id: 'gemini-cli',
    label: 'Gemini CLI',
    hint: '.gemini/settings.json in your project, or run: gemini mcp add',
    build: (url) => JSON.stringify({ mcpServers: { autoviz: { httpUrl: url } } }, null, 2),
  },
];

export function snippetById(id: string): McpSnippet {
  return MCP_SNIPPETS.find((s) => s.id === id) ?? MCP_SNIPPETS[0];
}

/**
 * Is this a connection URL a host will accept?
 *
 * Two properties, both learned the hard way (`Docs/26 §4.1`): hosts expect the
 * path to end `/mcp`, and the transport is HTTPS-only in every host that
 * documents it. A link failing either will be rejected with a message that does
 * not say which, so it is worth catching before the user pastes it anywhere.
 */
export function isUsableConnectionUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && parsed.pathname.endsWith('/mcp');
  } catch {
    return false;
  }
}
