# DAW Targets

`abletonian` should support multiple DAWs through one agent framework, but not
through one fake universal API. The correct abstraction is:

1. DAW-neutral musical intent.
2. Capability discovery.
3. DAW-specific adapters.

## Target Matrix

| Target slug | DAW | Initial adapter strategy | Expected depth |
| --- | --- | --- | --- |
| `ableton` | Ableton Live | Native Remote Script or AbletonOSC | Deep session/clip/device control |
| `fl-studio` | FL Studio | MIDI scripting bridge | Good transport, mixer, channel, pattern, playlist control; constraints around long-running scripts |
| `reaper` | REAPER | ReaScript and/or OSC | Deep project control; strong scripting story |
| `bitwig` | Bitwig Studio | Controller extension API | Good controller/project integration; Java extension packaging |
| `cubase-nuendo` | Cubase/Nuendo | MIDI Remote API script | Useful controller-style mapping; less ideal as a broad project-edit API |
| `logic-pro` | Logic Pro | Control surface, MIDI, Apple automation where safe | Limited and likely more workflow/control focused |
| `studio-one` | Studio One | MIDI/control-surface style adapter | Limited until a stable public automation surface is selected |
| `pro-tools` | Pro Tools | HUI/EUCON-style control where legally and technically viable | Conservative; likely transport/mix/control first |

## Shared Capability Vocabulary

Adapters should describe support using these coarse capabilities:

- `read_project_state`
- `transport_control`
- `track_management`
- `clip_or_pattern_editing`
- `midi_note_editing`
- `mixer_control`
- `device_or_plugin_control`
- `browser_or_preset_search`
- `arrangement_editing`
- `undo_checkpoint`
- `export_or_render`

The MCP server can use these capabilities to plan safely and tell the user when
a target DAW cannot perform a requested operation directly.

## Source Notes

- FL Studio documents Python MIDI scripting, with modules for playlist,
  channels, mixer, patterns, arrangement, UI, transport, device, plugins, and
  general functions.
- REAPER documents OSC control surfaces and ReaScript. Its ReaScript API is
  extended frequently, and REAPER can generate up-to-date API documentation from
  the Help menu.
- Bitwig describes an Open Controller Extension API and community controller
  extensions.
- Steinberg documents a JavaScript MIDI Remote API for Cubase/Nuendo controller
  integrations.

These are different surfaces, so adapter quality will vary by DAW.
