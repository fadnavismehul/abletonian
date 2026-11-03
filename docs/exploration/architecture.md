# abletonian Architecture

`abletonian` is split into four layers.

## MCP Layer

The MCP layer exposes a small number of agent-oriented tools and resources. It
owns naming, configuration, schemas, and user-facing descriptions.

Default server name: `abletonian`.

Configured server name:

```bash
abletonian --agent-name live-room
```

The target DAW is configured separately:

```bash
abletonian --target-daw fl-studio
```

The agent name is the public identity. The target DAW controls adapter behavior.

## Intent Layer

The intent layer maps musician-facing requests into a DAW-neutral operation
model: read project state, create material, edit MIDI, adjust mix state, load
devices, and control transport.

Adapters can decline or degrade operations when their host DAW does not expose a
safe API for the requested action.

## Bridge Layer

The bridge layer speaks to a DAW-specific adapter. The first protocol boundary
uses length-prefixed JSON frames:

```json
{
  "id": "request-id",
  "method": "daw.health",
  "params": {
    "target_daw": "ableton"
  }
}
```

Responses mirror the same ID:

```json
{
  "id": "request-id",
  "ok": true,
  "result": {}
}
```

Length-prefixing avoids the ambiguous JSON stream parsing issues common in
prototype socket bridges. Request IDs make concurrent clients and eventful DAWs
tractable later.

## DAW Adapter Layer

This layer can be implemented in more than one way:

- Native Ableton Remote Script adapter.
- Ableton Extensions SDK adapter (planned second Ableton adapter).
- AbletonOSC adapter.
- FL Studio MIDI scripting adapter.
- REAPER ReaScript or OSC adapter.
- Bitwig controller extension adapter.
- Cubase/Nuendo MIDI Remote adapter.
- Test/fake adapter for CI and agent evaluation.

The MCP and intent layers should not care which adapter is active, except for
capability discovery.

Since RFC 0003 this holds in the Python process: the MCP tools in
`src/abletonian/server.py` call a `DawAdapter`
(`src/abletonian/adapters/base.py`) through one `SafetyPolicy`
(`src/abletonian/policy.py`), which applies each operation's safety class,
confirm rule and capability check. `RemoteScriptAdapter` and
`FakeAbletonAdapter` are the two implementations; contract tests check they
agree. See [RFC 0003](../rfcs/0003-daw-adapter-and-safety-policy.md).
