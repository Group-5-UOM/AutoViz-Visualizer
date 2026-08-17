/**
 * The setup snippets the Connections panel hands a user.
 *
 * These are contracts with other people's software. Claude Desktop and Gemini
 * CLI read differently-shaped config files, and a wrong key name fails the way
 * integrations always fail — silently, with our server never contacted and
 * nothing anywhere to say why. The shapes are what is pinned here, not the
 * rendering.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MCP_SNIPPETS,
  isUsableConnectionUrl,
  snippetById,
} from '../src/lib/mcpSetup.ts';

const URL_ = 'https://autoviz.duckdns.org/c/abc123/mcp';

test('the plain URL snippet is the URL, untouched', () => {
  assert.equal(snippetById('url').build(URL_), URL_);
});

test('Claude Desktop gets mcpServers.autoviz with type and url', () => {
  const parsed = JSON.parse(snippetById('claude').build(URL_));
  assert.deepEqual(parsed, { mcpServers: { autoviz: { type: 'http', url: URL_ } } });
});

test('Gemini CLI gets mcpServers.autoviz with httpUrl', () => {
  // Not `url` — Gemini CLI names this key differently, and getting it wrong
  // produces a config that parses and never connects.
  const parsed = JSON.parse(snippetById('gemini-cli').build(URL_));
  assert.deepEqual(parsed, { mcpServers: { autoviz: { httpUrl: URL_ } } });
});

test('every snippet embeds the exact URL it was given', () => {
  for (const snippet of MCP_SNIPPETS) {
    assert.ok(
      snippet.build(URL_).includes(URL_),
      `${snippet.id} dropped or altered the URL`,
    );
  }
});

test('every snippet says where it goes', () => {
  // A config blob with no filename beside it is a puzzle, not instructions.
  for (const snippet of MCP_SNIPPETS) {
    assert.ok(snippet.hint.length > 0, `${snippet.id} has no hint`);
  }
});

test('an unknown snippet id falls back rather than throwing', () => {
  assert.equal(snippetById('does-not-exist').id, MCP_SNIPPETS[0].id);
});

// --- URL shape ---------------------------------------------------------------

test('a well-formed connection URL is accepted', () => {
  assert.equal(isUsableConnectionUrl(URL_), true);
});

test('the path must end /mcp', () => {
  // Hosts append or normalise this suffix; a key at the end would be eaten.
  assert.equal(isUsableConnectionUrl('https://autoviz.duckdns.org/c/abc123'), false);
});

test('http is rejected — every host that documents it requires TLS', () => {
  assert.equal(isUsableConnectionUrl('http://autoviz.duckdns.org/c/abc123/mcp'), false);
});

test('garbage is rejected rather than throwing', () => {
  assert.equal(isUsableConnectionUrl('not a url'), false);
  assert.equal(isUsableConnectionUrl(''), false);
});
