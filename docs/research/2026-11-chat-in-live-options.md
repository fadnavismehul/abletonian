# Chat with Claude inside Live: existing options, November 2026

**Date:** 2026-11-03
**Question:** The owner wants a chat box inside Ableton Live, as a Max for
Live device, where Claude Code (with his existing login) uses abletonian's
tools. Is there an MIT project we can reuse instead of building one?
**Method:** Web search, then a read of each candidate's source in a local
clone. Nothing was installed or run. Linear MEH-28.

## Summary

No existing project fits as is. The design that fits is the one
`djspilot/ableton-llm-mcp` sketches: a Max for Live device whose
`node.script` starts the local `claude` CLI and shows a `jweb` chat. That
project cannot be reused as it stands (no licence file, and any web page can
drive it). Producer Pal is mature and MIT, but its chat is a browser page,
it uses API keys rather than a Claude Code login, and it talks only to its
own tools.

Recommendation: build a small device of our own, following djspilot's
shape, with the security fixes below. It needs an RFC first, as a new
user-facing surface (AGENTS.md). Until then, Claude Desktop or Claude Code
beside Live already works with abletonian.

## Candidates

### djspilot/ableton-llm-mcp

- **What:** `bridge.js` (about 290 lines) in `node.script` runs a local
  HTTP/SSE server; `ui/` in `jweb` is the chat. It starts
  `claude --print --output-format stream-json --verbose
  --include-partial-messages` with the prompt on stdin, without a shell.
- **Licence:** the README says "MIT", but there is no LICENSE file and no
  copyright holder. We cannot copy code until upstream adds one.
- **Maturity:** 4 commits, all on 2026-05-06, no tests, no built `.amxd`.
  Replies render empty at HEAD: the server sends a named SSE event and the
  UI checks a different field (`bridge.js:166` against `ui/app.js:121`).
- **Security:** binds `127.0.0.1`, but has no token, no Origin or Host check,
  and sends `Access-Control-Allow-Origin: *`. Any web page in the owner's
  browser could start `claude` and read the reply, and DNS rebinding works.
- **Fit:** no working directory is set, so abletonian is only visible if
  registered with `claude mcp add -s user`. In `--print` mode no permission
  prompt can be answered, so tool calls are denied unless allowlisted.
  History is re-sent as flattened text each turn instead of `--resume`.

### Producer Pal (adamjmurray/producer-pal)

- **Licence:** MIT, "Copyright (c) 2025-2026 Adam Murray and Producer Pal
  contributors". Bundled libraries are MIT, Apache 2.0 or ISC.
  `TRADEMARK.md` reserves the name and logo, so a fork must be renamed.
- **Maturity:** releases v1.4.8 to v2.5.0, last commit 2026-10-27, about
  1,264 test files, CI with lint, typecheck, coverage and mutation tests.
  Essentially one maintainer.
- **Chat:** "Open Chat UI" launches a page in the default browser; the
  device has no `jweb`. Backends are API keys (Anthropic, Gemini, OpenAI,
  Mistral, OpenRouter, Vercel) or local models; no Claude Code or Agent SDK
  login. Keys are kept in browser storage.
- **Tools:** the chat talks only to Producer Pal's own MCP server and
  `ppal-*` tools. Its safety model groups each tool call as one undo step
  but has no confirmation gate for deletes.
- **Risk:** the main server listens without binding to localhost, and the
  code describes MCP and tool endpoints as reachable from the LAN with no
  auth.
- **Fit:** at most, its MIT chat front-end (`webui/`) could be borrowed as a
  starting point, with its notices kept and its name removed.

### jpoindexter/ableton-mcp

MIT, a Max for Live device with a chat in Live's device view, but the chat
reaches providers through API keys and uses its own tools. Not reviewed in
depth.

## What our own device would need

1. `node.script` starts `claude` in a dedicated project folder, with
   `--permission-mode default`, `--strict-mcp-config --mcp-config` naming
   only abletonian, and `--allowedTools` limited to abletonian's tools.
   Destructive tools stay behind abletonian's own `confirm=true`, which the
   model asks the user for in the chat.
2. A random token for each launch, sent by the `jweb` page on every request;
   Host and Origin checks; no wildcard CORS; JSON only.
3. `--resume <session_id>` for multi-turn chat, from the stream-json init
   event.
4. Tool calls and refusals shown in the chat, one run at a time, a timeout,
   and the child stopped when the page closes.
5. A built `.amxd` in releases. Needs Live Suite, or Standard with Max for
   Live, so it is an extra on top of the main features (MEH-19, answer 2).

Unverified, to check in a spike: whether Node for Max can start `claude`
with the user's PATH and login, and whether a device panel is large enough
or a floating `jweb` window is needed.

## Sources

- https://github.com/djspilot/ableton-llm-mcp (source read at HEAD on
  2026-11-03)
- https://github.com/adamjmurray/producer-pal (source read at HEAD on
  2026-11-03; producer-pal.org was not reachable from the research
  environment)
- https://github.com/jpoindexter/ableton-mcp (README only)
- https://cycling74.com/forums/producer-pal-mcp-server-running-in-node-for-max-to-control-ableton-live
