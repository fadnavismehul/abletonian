# RFC 0004: Bridge port and per-install key

**Status:** Accepted  
**Created:** 2026-11-03  
**Owner:** @fadnavismehul  
**Tracking issue:** [#37](https://github.com/fadnavismehul/abletonian/issues/37)

## Summary

Move the bridge off port 9877, and make the Remote Script accept requests
only from callers that know a key stored on this computer. Musicians notice
one thing: after upgrading, they reinstall the Remote Script once, as for any
Remote Script change. This is recommendation P3 of the
[landscape review](../research/2026-11-landscape-and-direction-review.md),
and the owner approved the port change on 2026-11-03 (Linear MEH-19).

## Motivation

1. **Port 9877 is shared.** `ahujasid/ableton-mcp`, `wstierhout/ableton-live-mcp`
   and LiveMCP all listen on 9877 inside Live. With any of them enabled,
   abletonian either fails to start its listener or sends framed requests to
   a server that does not speak its protocol. Both look like random errors to
   a musician.
2. **Any local program can edit the Set.** The listener is bound to
   `127.0.0.1`, but it accepts every connection. `SECURITY.md` says so today.
   Every Extensions SDK competitor in the review checks a token.

## Design

### 1. New default port: 39877

Both sides change together: `PORT` in `remote_scripts/Abletonian/bridge_server.py`
and `DEFAULT_BRIDGE_PORT` in `src/abletonian/config.py`. The number is 9877
with a 3 in front, so it is easy to remember. It is checked against every
project listed in the review: 9877, LivePilot's 9878, ntworm's 9888 and 9889,
and AbletonOSC's UDP 11000 and 11001. It is below the range operating systems
hand out for temporary ports (49152 and up). **Not checked:** the IANA
registry. If a clash turns up, only these two constants change.

`--bridge-port` and `ABLETONIAN_BRIDGE_PORT` keep working for the server. The
Remote Script's port stays fixed, because Live gives a Remote Script no
settings screen.

### 2. A per-install key

- **Where it lives:** a file at `~/.abletonian/bridge_key`, which on Windows
  is `%USERPROFILE%\.abletonian\bridge_key`. Both sides use
  `os.path.expanduser`, from the standard library.
- **Who creates it:** the Remote Script, when it starts in Live and the file
  is missing. It writes 32 random bytes as hex (`secrets.token_hex`), with
  file mode 0600 where the OS supports it. The server never writes the file,
  so whatever Live is using is the truth.
- **How it is sent:** every request frame gets one new top-level field,
  `"key": "<hex>"`. The server reads the file for each request; it is small,
  and this means a new key is picked up without a restart.
- **How it is checked:** on the socket thread, before anything is scheduled
  on Live's main thread, using `hmac.compare_digest`. If the key does not
  match its cached copy, the Remote Script reads the file once more, in case
  it was replaced, and only then refuses. A refusal never touches Live and
  returns error code `unauthorized`.
- **What the musician sees on a refusal:** "Live's Abletonian Remote Script
  did not accept this computer's key (~/.abletonian/bridge_key). Reinstall
  the Remote Script, then switch its Control Surface slot to None and back."
- **No key file on the server side:** "No bridge key found at
  ~/.abletonian/bridge_key. Open Live with the Abletonian Remote Script
  enabled once; it creates the key."

### 3. Protocol version and mismatched versions

`PROTOCOL_VERSION` becomes `abletonian.bridge.v2`, because a request without
`key` is now refused. The port change separates old and new installs: an old
server and a new Remote Script never meet, and neither do a new server and an
old Remote Script. The client's "could not connect" message gains one
sentence: "If you upgraded abletonian, reinstall the Remote Script."

### 4. Dropped from the review: "health as the required first frame"

The client opens one connection per request (`BridgeClient.request`), so
there is no session for a first frame to open. The key gives the protection
that rule was meant to give. `check_bridge_health` still validates
`protocol_version` and `adapter_type`.

### Safety class

Not an operation. It adds a refusal before any Live call, so it can only make
the bridge do less.

## What the key does and does not protect

- **It does stop** any other local program that does not have the key from
  changing the Set. That covers other MCP servers, scripts, and tools that
  probe local ports.
- **It does not stop** a program running as the same user, because that
  program can read the file, and nothing short of OS sandboxing could. The
  listener stays on `127.0.0.1`, so the network cannot reach it.

`SECURITY.md` will say exactly this.

## Safety and backout

- Reverting the implementation PR and reinstalling the Remote Script
  restores today's behaviour. The key file can be left in place, or deleted.
- If the key check misbehaves in Live, every request is refused before it
  reaches Live, so the Set cannot be harmed. The failure is closed.

## Verification

1. Remote Script tests: a missing, wrong or right key, with the wrong key
   checked before anything is scheduled; the key file created on first start
   with mode 0600; a replaced key picked up without a restart.
2. Client and server tests: the key is sent on every frame, the two messages
   above appear for a missing file and for `unauthorized`, and the new
   default port is used.
3. A run in Live on the Mac, through the validate-in-live skill:
   - The listener comes up on 39877.
   - A request without the key is refused, and Live's Undo History does not
     grow.
   - Deleting the key file and switching the slot creates a new key, and the
     server works with it without a restart.
   - With another project's Remote Script enabled on 9877, abletonian still
     works.

## Alternatives

1. **Keep 9877 and only detect the clash.** This fixes the confusing errors
   but not the clash itself. Two scripts still cannot both run.
2. **A key in an environment variable.** Live does not reliably pass the
   environment to Remote Scripts, and the user would have to set it on both
   sides.
3. **A Unix socket or named pipe instead of TCP.** That would mean different
   code for macOS and Windows inside Live's Python, which is more Live-side
   code to validate for little gain over the key.
4. **Ask the musician to type a code, as pairing.** This is the most secure
   option, but it adds a step to every install. The threat is local, so the
   key file is enough.

## Unresolved questions

1. Whether to accept requests without a key for one release, behind a
   setting. Proposed: no, because the port change already separates old and
   new installs.

## Implementation notes

Code: `BridgeKey`, `_check_key` and `PORT` in
`remote_scripts/Abletonian/bridge_server.py` (adapter 0.6.0);
`DEFAULT_BRIDGE_KEY_PATH` and `BridgeClient._read_key` in
`src/abletonian/bridge/client.py`; `DEFAULT_BRIDGE_PORT` in
`src/abletonian/config.py`. Tests: `tests/test_remote_script_key.py`, which
also checks that both sides share the port, key path and protocol version.

- 2026-11-03: If the key file is invalid (fewer than 32 lowercase hex
  characters), the Remote Script replaces it with a new key. It writes a
  temporary file first and then moves it into place.
