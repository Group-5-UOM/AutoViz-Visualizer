# 26 — Remote MCP Access: "Connect AutoViz to Gemini"

**16 August 2026. Phases 1, 2 and 3 are built. Phases 0, 4 and 5 are not.**

> **Status.** The endpoint is serving on the production host right now:
> `POST https://autoviz.duckdns.org/c/<key>/mcp` returns **401** for an unknown key, which means
> nginx, the auth middleware, the transport and the migration are all in place. What is missing
> The Connections panel now ships too, so a key can be minted from the UI — but **that build is
> not deployed yet**; the live site still serves the previous frontend. What remains is a
> deployment and a demonstration against a real host (Phase 4). A running tally is in §6.

The idea: a user opens **Settings → Connections**, clicks *Generate link*, gets a URL, and pastes
it into Gemini (or Claude, or any MCP host) as a custom MCP server. From then on that host can
upload, profile, query and chart *their* AutoViz data using the host's own model.

This is the highest-leverage feature left in the project, because it is the one that makes the
architecture's central bet visible. AutoViz was built **MCP-first** — Doc 09's five layers put the
MCP server beside the web app, not underneath it — and to date the only MCP host has been a
developer's local stdio process. A shareable link turns "MCP-first" from a design claim into a
demonstrable one.

Everything below was verified on 16 August against Google's documentation, the MCP specification,
the running EC2 host over SSH, and the code.

---

## 1. What is true today

### The deployment (verified by SSH to `ec2-user@autoviz.duckdns.org`)

| | |
|---|---|
| TLS | **Valid Let's Encrypt certificate**, managed by certbot, nginx terminating on :443 |
| nginx routes | `/` → static frontend · `/api/` → `localhost:8000` · `/health` → backend · **`/c/` → `localhost:8000/c/`, added 16 Aug, unbuffered, with the access-log path redacted** |
| API | `autoviz-api-1` container, port 8000 |
| Database | `autoviz-db-1` (postgres:16), listening on 5432 **inside Docker only** |
| Port 8000 externally | **Not reachable** — `curl http://autoviz.duckdns.org:8000/health` fails. Docker binds `0.0.0.0:8000` but the AWS security group blocks it, so nginx is the only way in |

**The TLS story is already solved**, which removes the single biggest obstacle. Gemini requires
HTTPS and the host already serves it on a real domain.

> One defence-in-depth note while we are here: the API container publishes `0.0.0.0:8000` and is
> saved only by the security group. Binding it to `127.0.0.1:8000` in the compose file would make
> nginx the only path by construction rather than by cloud configuration. Not urgent, not related
> to this feature, worth doing while touching the deployment.

### What the MCP server can and cannot do today

| | |
|---|---|
| Transport | stdio **and** Streamable HTTP. `mcp.run()` still serves stdio; `streamable_http_app()` is mounted at `/c` when `AUTOVIZ_REMOTE_MCP=1` |
| Library support | `mcp==1.28.1` — `streamable_http_app()` and `stateless_http` already existed, so the transport was configuration, not a rewrite |
| Tools | **11 in `host`** (the default for a new key), 7 in `default`, 18 in `advanced` |
| **User scoping** | **Done.** No `REGISTRY` reference remains in the MCP layer; every tool resolves `current_registry()` |

*This table described the state before the work. Both rows that were blockers are now closed —
§3 records what the problem was and how it was fixed, because the reasoning is the reusable part.*

### "Gemini" is three different products with three different rules

This matters more than it sounds, because the surface you had in mind —
**Settings → Connected Apps → "Custom apps for Spark" → `https://your-app-link.com/mcp`** — is
the *most* restricted of the three, and not in the way I first assumed.

| | **Gemini Spark** (the one you meant) | **Gemini CLI** | **Gemini Enterprise** |
|---|---|---|---|
| Where | `gemini.google.com` → Connected Apps | Terminal, `gemini mcp add` | Google Cloud connector |
| Transport | Standard MCP | HTTP / SSE | **StreamableHTTP only** |
| Auth | **DCR preferred**, manual credentials as fallback | OAuth 2.0 | **No-auth or OAuth 2.0** |
| **Availability** | **US only · personal Google account only · 18+ · English only · "Keep Activity" must be on** | Anywhere | Org-policy FQDN allowlist |

Sources: [Spark custom apps](https://support.google.com/gemini/answer/17209137?hl=en&co=GENIE.Platform%3DDesktop) ·
[Gemini CLI](https://gofastmcp.com/integrations/gemini-cli) ·
[Enterprise connector](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/custom-mcp-server/set-up-custom-mcp-server).

**Two findings change the design.**

**1. Spark is US-only and personal-account-only.** Google's help page is explicit: *"Be 18 or over
and in the US"*, *"Sign in to the Gemini app with a personal Google Account"* (work/school not
supported), English only, and Gemini *"can't connect to custom apps"* with Keep Activity off.
**From Sri Lanka, on a university account, Spark custom apps are very likely not available at
all** — see §8, because this decides which host the milestone demo runs against.

**2. Spark expects OAuth, not a bare link.** Its flow is: *"If the server doesn't support Dynamic
Client Registration, next to 'Advanced features,' click Show more, then enter your credentials."*
DCR is the preferred path and manual client credentials are the fallback — both are OAuth. It
also requires that *"the MCP server must follow the standard MCP specifications"*, and the
specification mandates OAuth 2.1 for remote servers.

Spark's docs do not describe a no-authentication option at all. A capability URL would probably
still connect — the MCP OAuth flow is only triggered by a `401` carrying `WWW-Authenticate`, and
a server that never returns one is simply treated as open — but that is **inference from the
protocol, not a documented Spark behaviour**, and it is the kind of inference that breaks
silently on someone else's release schedule.

**So the honest position is:** a capability URL is a legitimate design for Claude Desktop and
Gemini CLI, and a *gamble* for Spark. Spark's documented path is OAuth 2.1 + DCR.

### What the MCP specification requires

Per the November 2025 revision, **any MCP server reachable over the internet must implement
OAuth 2.1 with PKCE**, must publish
[RFC 9728 Protected Resource Metadata](https://mojoauth.com/blog/how-mcp-authorization-actually-works-oauth-2-1-resource-servers-and-resource-indicators)
at `/.well-known/oauth-protected-resource`, and acts as an OAuth **resource server** — it
validates tokens and never issues them. The
[2026-07-28 revision](https://workos.com/blog/mcp-2026-spec-agent-authentication) deprecates
Dynamic Client Registration in favour of Client ID Metadata Documents, keeping DCR for at least
twelve months.

**AutoViz today is an OAuth *client*** — `api/oauth.py` signs state and exchanges codes with
Google and GitHub so people can log in. Being an OAuth *resource server* for MCP is a different
and larger job, and nothing in the codebase does it yet.

---

## 2. The tension, stated plainly

> The idea — *"in settings, the user creates their own link"* — is a **capability URL**: a secret
> embedded in the address, where possession of the link is the authorisation. It is one afternoon
> of work, it is explicitly supported by Gemini Enterprise's "No Authentication" mode, and it
> works with Claude Desktop and Gemini CLI today.
>
> It is also **not MCP-spec compliant** (remote servers must do OAuth 2.1), and **not Spark's
> documented path** (DCR or manual credentials).

Both halves are true, and the resolution is not to pick one. It is to notice that they serve
different purposes on different timescales:

- **The capability URL is the demo.** It is buildable before 18 August, it proves the
  architecture, and it works against a host you can actually reach from Sri Lanka.
- **OAuth 2.1 + DCR is the product.** It is what Spark wants, what the spec requires, and what
  makes the feature real for users who are not you.

The plan below ships the first and schedules the second, rather than pretending the first is
sufficient or that the second is affordable this week.

---

## 3. The blocker that had to be cleared first · ✅ closed

**Kept as written, because the reasoning outlived the fix.** This was the gate on serving MCP over
HTTP at all, and the same trap waits for anyone adding a second transport to a process-wide cache.

Every MCP tool resolves datasets through the global `REGISTRY` singleton:

```python
# backend/src/autoviz/mcp/server.py:50
from autoviz.services.registry import REGISTRY
...
record = REGISTRY.get(dataset_id)      # no notion of who is asking
```

That is correct for stdio, where the process *is* the user. Over HTTP it is not: the registry is
a process-wide LRU cache shared by every request, so **any MCP link could read any dataset any
other user had touched**, simply by guessing or observing a `dataset_id`. `list_datasets` would
enumerate them.

This is the long-standing P0 that [`Docs/21`](21-Project-Status.md) has carried since July —
"datasets are user-owned, agent threads are not" — arriving where it finally bites.

**The fix already exists on the HTTP side and just has to be reused.** `storage/repository.py`
describes `resolve_dataset` as *"the ownership + lazy-reload gate every dataset [access goes
through]"*, and the FastAPI routes pair it with `get_current_user`. The MCP path needs the same
gate:

1. A request-scoped `ContextVar` holding the authenticated `user_id` for the current MCP call.
2. `mcp/context.py: current_registry()` returning a **per-user registry view** whose loader is
   bound to that user — a miss loads from `repository.resolve_dataset(db, dataset_id, user_id)`,
   and a dataset the user does not own resolves to `None`, producing the existing
   `UNKNOWN_DATASET` error rather than a leak.
3. Every `server.py` tool takes its registry from that function instead of importing the
   singleton.

**Acceptance test, and it was not optional:** two users, two links, one dataset each. User A's
link must return `UNKNOWN_DATASET` for user B's `dataset_id`, and `list_datasets` on A's link must
not mention B's.

✅ **Green** — [`tests/test_mcp_scoping.py`](../backend/tests/test_mcp_scoping.py), 10 tests. And
verified non-vacuous: disabling scoping makes 7 of the 10 fail, including all five cross-user leak
cases. A test that cannot fail is not a gate.

---

## 4. The design

### 4.1 The link

```
https://autoviz.duckdns.org/c/<key>/mcp
                              │      └── the conventional endpoint every host expects
                              └── 32 bytes of CSPRNG, base64url, shown once
```

**The key goes in the middle, and the path ends `/mcp`.** Every host's placeholder is
`https://your-app-link.com/mcp`, Gemini Enterprise's docs say the URL *"often ends with `/mcp`"*,
and a client that appends or normalises that suffix would break a URL ending in the secret. My
first draft put the key last (`/mcp/<key>/`) and would have tripped over exactly that.

The secret sits in a **path segment**, not a query string — query strings are the more likely of
the two to end up in referrer headers and third-party logs, and a path segment survives the proxy
hop cleanly.

`/c/` rather than `/mcp/` as the prefix keeps the credentialed route distinct from the
future spec-compliant one, so `/mcp` stays free for the OAuth-protected endpoint in Phase 5 and
both can run side by side during migration.

A new table, so MCP keys are not confused with login sessions:

| `mcp_keys` | |
|---|---|
| `id` | uuid |
| `user_id` | FK → `users`, cascade delete |
| `token_hash` | **SHA-256 of the key.** The plaintext is shown once at creation and never stored — a database dump must not yield working links |
| `label` | user-supplied, e.g. "Gemini on my laptop" |
| `profile` | `host` \| `default` \| `advanced` — which tool surface this key exposes. New keys default to `host` (§4.4) |
| `created_at`, `last_used_at`, `expires_at`, `revoked_at` | lifecycle |

`last_used_at` matters more than it looks: it is the only way a user can tell whether a link they
have forgotten about is still being used.

### 4.2 The transport

`mcp==1.28.1` already provides it:

```python
mcp.settings.stateless_http = True        # no server-side session affinity
# Mounted under the credentialed prefix; the middleware in §4.3 strips /c/<key>.
app.mount("/c", mcp.streamable_http_app())
```

`stateless_http` is the right setting here: the server sits behind nginx, may be replicated, and
must not depend on a client returning to the same worker.

nginx needs one location block, and it must **not** buffer — Streamable HTTP streams responses:

```nginx
location /c/ {
    proxy_pass http://localhost:8000/c/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;          # streaming responses
    proxy_read_timeout 300s;
}
```

### 4.3 Authentication

An ASGI middleware in front of the mounted app:

1. Take the `<key>` path segment, SHA-256 it, look it up in `mcp_keys`.
2. Reject unknown, revoked or expired keys with `401` — in **constant time**, so the endpoint is
   not a timing oracle for valid keys.
3. Bind `user_id` and `profile` into the request-scoped context from §3.
4. Update `last_used_at` (throttled — once a minute is plenty, and avoids a write per tool call).

Rate limiting per key belongs here too, because this endpoint is unauthenticated in the
conventional sense and publicly reachable.

### 4.4 Which tools to expose — and why the answer is *fewer*

**A new key defaults to the `host` profile — 11 tools, and none of them ours to think with.**

The reasoning is specific to this feature rather than general caution. Two tools in `default` —
`analyze` and `answer_clarification` — run *our* LangGraph agent and *our* Gemini planner. Called
from inside Gemini, that is Gemini asking AutoViz to ask Gemini: double latency, double cost, and
the host's model reduced to a passthrough. The whole point of MCP is that the **host's** model
plans and **our** tools compute deterministically.

So the profile offered to external hosts should be narrower still — a third profile:

| `host` profile | Why |
|---|---|
| `register_dataset`, `list_datasets` | The host needs to find data |
| `get_dataset_schema`, `get_dataset_profile`, `preview_dataset` | What it needs to plan against |
| `analyze_data_quality` | A host that cannot see the data's problems plans around them badly — the existing rationale in `server.py` applies doubly to a foreign model |
| `validate_analysis_plan`, `execute_analysis` | The deterministic core: closed grammar → DuckDB → provenance |
| `recommend_chart_type`, `generate_chart`, `export_chart` | The rendering half |

That is **11 tools, and no LLM of ours in the loop** — the host plans, AutoViz validates and
computes, and the invariant from [`Docs/09`](09-System-Architecture.md) holds across the
boundary: *the LLM only plans; it never computes a number.* It now holds for **someone else's**
LLM too, which is a stronger claim than the project has been able to make so far.

`analyze` stays available under `advanced` for hosts that genuinely want the agent.

### 4.5 The settings UI · ✅ built — see Phase 3

**Settings → Connections**

- *Generate connection link* → label, profile, optional expiry → **the key is shown exactly once**,
  with a copy button and a plain warning that it will not be shown again.
- A list of existing keys: label, profile, created, **last used**, and a Revoke button
  (`ConfirmDialog`, which [`Docs/22`](22-Export-and-UI-States.md) already established as the
  pattern — no `window.confirm`).
- Copy-paste setup snippets per host: the raw URL for Gemini Enterprise's connector form, and a
  `.gemini/settings.json` block for Gemini CLI.

---

## 5. Security: what this costs, stated honestly

A capability URL is a **bearer credential in an address bar**, and every property below follows
from that. None of it is a reason not to ship; all of it is a reason to be deliberate.

| Risk | Mitigation |
|---|---|
| The link leaks (screenshot, chat, shoulder-surf) and *is* the credential | Shown once · revocable · optional expiry · `last_used_at` visible · scoped to one user's data and a read-mostly tool set |
| It appears in nginx `access.log` on every request | **Change the log format for `/c/` to strip the path**, or the credential is written to disk thousands of times. This is easy to forget and is the single most likely real-world leak |
| Our own observability logs it | `observability.py` already hashes tool inputs and never logs raw arguments; the middleware must hold to that and log the **key id**, never the key |
| Brute force against the endpoint | 32 bytes of entropy is not guessable, but rate-limit per IP anyway and keep lookup constant-time |
| A stolen key acts as the user indefinitely | Expiry, revocation, and — the honest answer — this is exactly the property OAuth 2.1 exists to fix, which is why §6 Phase 2 is on the roadmap rather than "someday" |
| The key ends up in a public repo (`.gemini/settings.json` is a *file*) | Say so in the UI copy at generation time. This is the commonest way such tokens escape |

**One thing not to do:** do not reuse the existing login `sessions.token` as the MCP key. A
credential pasted into a third-party tool must be independently revocable without logging the
user out of their browser, and must carry a *narrower* scope than a full session.

---

## 6. Plan

### Phase 0 — Find out which host you can actually reach · **30 minutes, do this first**

Everything downstream assumes a host that will connect. Spark's eligibility rules make that an
open question, and the answer changes what Phase 4 demos — so spend half an hour before spending
four days.

0. Open `gemini.google.com` → Settings & help → Connected Apps. **Is "Custom apps for Spark" even
   visible** on your account, from Sri Lanka, on a university Google account? If it is not, Spark
   is out for the milestone and the demo host is **Claude Desktop** (no restrictions) or **Gemini
   CLI** (no restrictions).
1. Whichever host is available, confirm it will connect to *some* public MCP server before
   building AutoViz's. A known-good third-party server takes minutes and isolates "our server is
   wrong" from "this host will not connect from here".

### Phase 1 — Per-user scoping (the blocker) · ✅ **DONE, 16 August**

1. ✅ [`mcp/context.py`](../backend/src/autoviz/mcp/context.py) — `McpCaller` bound to a
   **ContextVar** (not a thread-local: the HTTP app is async and several requests share a
   thread, so a thread-local would hand one user's identity to another's coroutine), plus
   `ScopedRegistry` and `current_registry()`.
2. ✅ All 17 registry call sites in `server.py` rewritten — **no `REGISTRY` reference remains**
   in the MCP layer. Tools, resources and the pipeline lambda all resolve through
   `current_registry()`.
3. ✅ [`tests/test_mcp_scoping.py`](../backend/tests/test_mcp_scoping.py) — 10 tests. Suite
   **820 → 830**.

Two properties beyond "it passes":

**It fails closed.** A dataset with no ownership row is invisible to a scoped caller, rather than
treated as unowned-and-therefore-public. That is what stops a local stdio session's datasets
leaking into a remote one sharing the process.

**The gate is not vacuous.** Disabling scoping (`current_registry()` always returning the global)
was verified to fail 7 of the 10 tests, including all five cross-user leak cases. A test that
cannot fail is not a gate.

Unscoped behaviour is byte-for-byte unchanged: with no caller bound, `current_registry()` returns
the global `REGISTRY`, which is why the other 820 tests never noticed.

### Phase 2 — Transport and keys · ✅ **DONE and DEPLOYED, 16 August**

4. ✅ [`models/mcp_key.py`](../backend/src/autoviz/models/mcp_key.py) + migration
   [`009_mcp_keys`](../backend/alembic/versions/009_mcp_keys.py). Single head; DDL checked against
   Postgres offline, and the table now exists on the live database.
5. ✅ [`api/mcp_auth.py`](../backend/src/autoviz/api/mcp_auth.py) — pure-ASGI middleware (not
   `BaseHTTPMiddleware`, which buffers the body and would defeat a streaming transport).
6. ✅ Mounted at `/c` with `stateless_http = True`, **opt-in behind `AUTOVIZ_REMOTE_MCP=1`** — a
   publicly reachable, capability-authenticated endpoint should not arrive as a side effect of
   deploying. A test asserts it 404s when unset.
7. ✅ `host` profile — 11 tools.
8. ✅ nginx `location /c/` with `proxy_buffering off` **and the access-log redaction**, validated
   with `nginx -t` before reload. Verified live: a request with a key logs `/c/[redacted]`.
9. ✅ Beyond the original scope — `POST/GET/DELETE /auth/mcp-keys`, so Phase 3 is pure frontend.

**Tests: 830 → 864.** 34 new, including a real HTTP round trip through the middleware into the
MCP transport.

#### Four things only the real HTTP path revealed

Every unit test passed while the endpoint was entirely broken. Each of these cost a debugging
cycle and none would have been caught by testing the pieces:

| Symptom | Cause |
|---|---|
| Every request 401 | **Starlette hands a mounted ASGI app the *full* path**, prefix included — so the first segment read as the key was `c`. The middleware now strips its own mount prefix |
| `Task group is not initialized` | The Streamable HTTP **session manager must be started in the parent app's lifespan**. Mounting a sub-app does not run its lifespan |
| `run() can only be called once` | `streamable_http_app()` caches the manager on the FastMCP singleton, so a second `create_app()` in one process failed at startup. Each app now gets a fresh manager |
| `421 Invalid Host header` | MCP ships **DNS-rebinding protection on by default** and rejects any `Host` it was not told about — which would have rejected `autoviz.duckdns.org` in production too. Allowed hosts derive from `AUTOVIZ_API_PUBLIC_URL` |

The last one is the one worth remembering: it would have looked like a deployment problem and was
a library default.

### Phase 3 — Settings UI · ✅ **DONE, 16 August**

10. ✅ A **Settings page** at `/settings`, not a modal —
    [`SettingsPage.tsx`](../frontend/src/pages/SettingsPage.tsx) with an Account section and
    [`ConnectionsSection.tsx`](../frontend/src/components/settings/ConnectionsSection.tsx).
    Generate, show-once, list with **last used**, revoke behind `ConfirmDialog` (the pattern
    [`Docs/22`](22-Export-and-UI-States.md) established — no `window.confirm`). Deep-links via
    `/settings#connections`, so an instruction elsewhere can point straight at it.

    *It shipped as a modal first and that was the wrong shape.* Connections carries setup
    instructions for three different hosts, and a dialog has to be dismissed to consult anything
    else — exactly wrong for something you read **while** configuring another application. A page
    also gives the URL somewhere to live.

    One real layout bug came out of the first version: the Copy button was absolutely positioned
    over the code block, so a URL long enough to wrap ran underneath it and **the tail — the part
    you need — was covered**. The button now sits in its own bar above the code, where it cannot
    collide with text at any width.
11. ✅ [`lib/mcpSetup.ts`](../frontend/src/lib/mcpSetup.ts) — the per-host setup snippets, pulled
    out of the component **because they are contracts with other people's software**, not
    presentation. Claude Desktop wants `{type, url}`; Gemini CLI wants `httpUrl`. A wrong key name
    fails the way integrations always fail: silently, with our server never contacted and nothing
    anywhere to say why. 10 tests pin the shapes — frontend suite **25 → 35**.

The show-once block is deliberately loud, and closing the panel clears the key from component
state. There is no path back to it: losing it means revoking and minting again, which the copy
says in those words.

### Phase 4 — Prove it, and say what it proves · ~half a day

10. Connect from a **host you can actually reach** — see Phase 0 — and run a full task end to end.
11. **Record it.** A 30-second clip of a foreign model driving AutoViz's tools is the single most
    persuasive artefact this project could put in the mid-evaluation deck — see
    [`Docs/25`](25-Mid-Evaluation-Presentation.md), where it would slot in beside the architecture
    slide as evidence that "MCP-first" was a real decision. **Record it regardless of which host
    cooperates**; the claim is "any MCP host", and Claude Desktop demonstrates that as well as
    Spark would.

### Phase 5 — OAuth 2.1 + DCR · ~1 week, and it is what Spark needs

Promoted from "someday" by the Spark findings in §1: this is not polish, it is the difference
between a link that works for you and a feature that works for users.

12. RFC 9728 Protected Resource Metadata at `/.well-known/oauth-protected-resource`.
13. Authorisation-server role or delegation, PKCE, resource indicators.
14. **Dynamic Client Registration**, because it is the path Spark prefers and the one that removes
    the manual-credentials step. Note the 2026-07-28 spec deprecates DCR in favour of Client ID
    Metadata Documents while keeping it for ≥12 months — so build DCR now, expect to add CIMD.
15. Keep capability URLs working alongside on `/c/`, marked "legacy" in the UI.

**Total to a working demo: about 3–4 days.** Phase 5 is a separate week and should not be
attempted before 18 August — but it should be scheduled, not deferred indefinitely, because
without it the feature only works for hosts that tolerate an unauthenticated server.

---

## 7. Decisions I need from you

| # | Decision | My recommendation |
|---|---|---|
| 0 | **Which host does the demo target?** | **Whichever Phase 0 says works.** Plan for Claude Desktop or Gemini CLI; treat Spark as a bonus, because its US/personal-account rules probably exclude you |
| 1 | Ship the capability URL now, or wait for OAuth? | **Ship it.** OAuth+DCR is a week and the milestone is in two days — but schedule Phase 5, because without it Spark stays out of reach even from the US |
| 2 | Default profile for a new key | **`host` (11 tools, no LLM of ours)** — §4.4. It is the version that demonstrates the architecture rather than duplicating it |
| 3 | Default expiry | **90 days**, user-overridable. Long enough not to annoy, short enough that an abandoned link dies |
| 4 | One key per user, or many? | **Many.** Separate keys per host is what makes revocation useful — kill the laptop's key without killing the phone's |
| 5 | Is `autoviz.duckdns.org` the final hostname? | If a real domain is coming, do it before people paste links into third-party tools, because those links will not follow a rename |

---

## 8. What could still stop this

**Gemini Spark may simply not be available to you.** This is now the top risk, and it is not
technical. Google's help page requires you to *"be 18 or over **and in the US**"*, to *"sign in
with a **personal** Google Account"* (work and school accounts are excluded), to have the app in
**English**, and to have **Keep Activity on**. A University of Moratuwa account fails the second
condition outright, and Sri Lanka fails the first.

**This does not stop the feature — it changes the demo host.** The thing being proved is "any MCP
host can drive AutoViz's tools", and:

- **Claude Desktop** — no geographic or account restriction, connects to remote MCP servers.
- **Gemini CLI** — no restriction either, `gemini mcp add`, and still genuinely *Gemini*, which
  matters if the demo narrative is about Gemini specifically.

Either is a complete demonstration. Spark is a nicer screenshot, not a better proof — and Phase 0
exists so this is discovered in half an hour rather than on the 17th.

**Do not solve this with a VPN.** Beyond the terms-of-service question, a demo that only works
through a tunnel is a demo that will fail in the room.

**Secondary risks, unchanged:** Gemini Enterprise requires org-policy FQDN allowlisting, which a
student account will not have; and a `duckdns.org` subdomain may be treated differently from a
first-party domain by enterprise allowlists. Both are reasons the Enterprise connector is the
least likely of the three to work, despite being the one with the clearest documentation.

---

*Sources: [Gemini Enterprise custom MCP server setup](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/custom-mcp-server/set-up-custom-mcp-server) ·
[Gemini CLI + FastMCP](https://gofastmcp.com/integrations/gemini-cli) ·
[MCP authorization: OAuth 2.1, resource servers, resource indicators](https://mojoauth.com/blog/how-mcp-authorization-actually-works-oauth-2-1-resource-servers-and-resource-indicators) ·
[The 2026-07-28 MCP spec update](https://workos.com/blog/mcp-2026-spec-agent-authentication) ·
[Configure MCP in an AI application](https://docs.cloud.google.com/mcp/configure-mcp-ai-application).
Infrastructure facts verified by SSH to the running host on 16 August 2026; code facts verified
against the working tree the same day.*
