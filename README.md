# abletonian

`abletonian` is a FOSS harness for musicians who let an AI agent work in their
DAW. It decides what an agent may do to a Live Set, how a change is proposed,
checked, applied and undone, and how the result is verified and recorded. It
ships as an MCP server. Ableton Live is the first target.

The part inside Live, today a Python Remote Script, is a replaceable adapter.
Ableton's Extensions SDK is planned as a second Ableton adapter, and other DAWs
come only after two Ableton adapters have proved the boundary between the
harness and the adapters. See
[`docs/research/2026-11-landscape-and-direction-review.md`](docs/research/2026-11-landscape-and-direction-review.md)
for why.

The repo, package, CLI, and default agent name are all `abletonian`. The agent
name can be parameterised for local workflows, multiple Ableton instances, or
branded downstream builds:

```bash
abletonian --agent-name studio-copilot
ABLETONIAN_AGENT_NAME=live-room abletonian
```

## What it is like to use

1. You ask in plain words in Claude Desktop, Claude Code, or another MCP
   client, for example "make the drums punchier".
2. abletonian reads the open Live Set. For bigger jobs, such as Drum Rack
   extraction, it shows a plan first: what will change, and anything risky.
3. You approve. Deletes always show what would go and ask first.
4. The change lands as one Live undo step, so one Undo takes it back (Remote
   Script 0.5.0 and later, checked in Live 12.4.16). Live keeps parameter
   changes in their own step, so a change that also inserts or renames
   something can take two.
5. You never pick a bridge. abletonian uses what is installed in Live and
   says plainly when it cannot do something.

Later, on Live Suite, the plan and the Macro Cockpit will also open in a
window inside Live from a right-click menu; other editions get the same view
in the browser. How the safety rules work is in
[`robustness-and-safety.md`](docs/engineering/robustness-and-safety.md).

## Current shape

- `abletonian` CLI entry point and MCP server over stdio.
- A Remote Script for Ableton Live 12 that reads and changes the open Set.
- A length-prefixed JSON bridge protocol with request IDs on `127.0.0.1`.
- Drum Rack extraction and a read-only Macro Cockpit as the first workflows.
- Local Ableton manual search with citations.
- A fake adapter and tests that need no Ableton.

`--target-daw` selects a DAW profile that describes the planned adapter for
another DAW. Only Ableton has an adapter today; other targets change what the
server reports, not what it can do.

## Usage

```bash
python -m pip install -e .
abletonian
```

Claude Desktop or another MCP client can start it over stdio:

```json
{
  "mcpServers": {
    "abletonian": {
      "command": "abletonian",
      "args": ["--agent-name", "abletonian", "--target-daw", "ableton"]
    }
  }
}
```

## Control the open Live Set

The Abletonian Remote Script reads and changes the Live Set that is open now:
tracks, groups, routing, mixer levels and sends, device parameters, names and
colours, and native device insertion with `Track.insert_device` (Live 12.3+).
Setup, the tool list, and how to register the server with Claude Code are in
[`docs/engineering/live-control.md`](docs/engineering/live-control.md).

## Ableton manual search

`search_ableton_manual` searches a local Markdown copy of the Live Reference
Manual and cites ableton.com section links. The manual is Ableton's copyright,
so it is not committed. Fetch it into `docs/ableton-manual/<major>/<edition>/`:

```bash
.venv/bin/python -m scripts.fetch_manual --live-major 12
```

Each run stores the edition Ableton publishes (for example `2026-10-01`) next
to older ones, so answers can be pinned to an edition.

## Configuration

| Setting | CLI | Environment | Default |
| --- | --- | --- | --- |
| Agent/server name | `--agent-name` | `ABLETONIAN_AGENT_NAME` | `abletonian` |
| Target DAW | `--target-daw` | `ABLETONIAN_TARGET_DAW` | `ableton` |
| Bridge host | `--bridge-host` | `ABLETONIAN_BRIDGE_HOST` | `127.0.0.1` |
| Bridge port | `--bridge-port` | `ABLETONIAN_BRIDGE_PORT` | `39877` |
| Bridge timeout | `--bridge-timeout` | `ABLETONIAN_BRIDGE_TIMEOUT` | `35.0` |
| Manual folder | | `ABLETONIAN_MANUAL_DIR` | `docs/ableton-manual` |
| Saved cockpits folder | `--cockpit-dir` | `ABLETONIAN_COCKPIT_DIR` | per-user data folder, `abletonian/cockpits` |

## Strategic Directions

Deep product and architecture options are collected in [`docs/exploration/strategic-directions.md`](docs/exploration/strategic-directions.md),
including Ableton-native panels, MCP Apps, local-first music memory, adapter-standard
work, performance tooling, education, collaboration, and custom micro-tool generation.

## DAW Targets

The first-class target is `ableton`. Other planned targets are described in
[`docs/exploration/daw-targets.md`](docs/exploration/daw-targets.md). They will not all support the same
operations: `abletonian` normalizes musical intentions and lets each adapter
advertise what it can actually do. REAPER is the likely second DAW, and work on
it waits until the Python core has a real adapter interface
([RFC 0003](docs/rfcs/0003-daw-adapter-and-safety-policy.md)).

## Related projects

`abletonian` is not the only way to drive Live from an AI agent, and it does
not try to cover the most of Live's API:

- Remote Script servers with broad coverage, such as
  [`ahujasid/ableton-mcp`](https://github.com/ahujasid/ableton-mcp) and
  [`wstierhout/ableton-live-mcp`](https://github.com/wstierhout/ableton-live-mcp).
  Both listen on port 9877. abletonian moved to 39877 (RFC 0004), so they no
  longer clash.
- Servers built on the Ableton Extensions SDK (Live 12 Suite beta), such as
  [`ulm0/ableton-live-mcp`](https://github.com/ulm0/ableton-live-mcp) and
  [`t1merickson/next-live-mcp`](https://github.com/t1merickson/next-live-mcp).
- [AbletonOSC](https://github.com/ideoforms/AbletonOSC), a general OSC
  control protocol for Live.

Section 4 of the
[landscape review](docs/research/2026-11-landscape-and-direction-review.md)
compares them as of November 2026.

## Contributing

Contributions are welcome, including from people who use coding agents. Start
with [`CONTRIBUTING.md`](CONTRIBUTING.md); agents should read
[`AGENTS.md`](AGENTS.md). You can help without writing code: running a
feature in your copy of Ableton Live and filing a Live validation report is one
of the most useful things a contributor can do.

## License

MIT. Ableton, FL Studio, REAPER, Bitwig, Cubase, Nuendo, Logic Pro, Studio One,
and Pro Tools are trademarks of their respective owners. This project is
independent and is not affiliated with or endorsed by those vendors.
