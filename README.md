# abletonian

`abletonian` is a FOSS DAW agent framework and MCP server for safer, musical
automation. Ableton Live is the first target, but the framework is designed for
FL Studio, REAPER, Bitwig, Cubase/Nuendo, and other DAWs through adapters.

The repo, package, CLI, and default agent name are all `abletonian`. The agent
name can be parameterised for local workflows, multiple Ableton instances, or
branded downstream builds:

```bash
abletonian --agent-name studio-copilot
ABLETONIAN_AGENT_NAME=live-room abletonian
abletonian --target-daw fl-studio
```

## Direction

`abletonian` is intended to be a musician-facing agent layer rather than a giant
bag of raw DAW remote-control tools. The first design goals are:

- Keep the MCP surface small, typed, and legible.
- Prefer non-destructive operations and explicit undo/checkpoint flows.
- Treat DAW project/session state as context resources, not just tool output.
- Separate the MCP server from DAW-specific bridge protocols.
- Make the agent identity configurable without requiring forks.
- Let each DAW adapter advertise its actual capabilities and constraints.

## Early Shape

The initial scaffold includes:

- `abletonian` CLI entry point.
- Configurable MCP/agent name through `--agent-name` or `ABLETONIAN_AGENT_NAME`.
- Configurable target DAW through `--target-daw` or `ABLETONIAN_TARGET_DAW`.
- A length-prefixed JSON bridge protocol with request IDs.
- A tiny starter MCP server with DAW profiles, health, and planning tools.
- Unit tests for config and bridge framing.

The Ableton bridge implementation is intentionally still a boundary, not a pile
of commands. This keeps room for native Remote Script, AbletonOSC, FL Studio MIDI
scripting, REAPER ReaScript/OSC, Bitwig controller extensions, and other
adapter strategies.

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
| Bridge port | `--bridge-port` | `ABLETONIAN_BRIDGE_PORT` | `9877` |
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
advertise what it can actually do.

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
