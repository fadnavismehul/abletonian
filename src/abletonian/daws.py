"""DAW target profiles for abletonian."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TARGET_DAW = "ableton"


@dataclass(frozen=True)
class DawProfile:
    """A DAW target and the adapter strategy abletonian should use for it."""

    slug: str
    name: str
    adapter_strategy: str
    maturity: str
    expected_depth: str
    capabilities: tuple[str, ...]
    constraints: tuple[str, ...]
    docs: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return {
            "slug": self.slug,
            "name": self.name,
            "adapter_strategy": self.adapter_strategy,
            "maturity": self.maturity,
            "expected_depth": self.expected_depth,
            "capabilities": list(self.capabilities),
            "constraints": list(self.constraints),
            "docs": list(self.docs),
        }


SUPPORTED_DAWS: dict[str, DawProfile] = {
    "ableton": DawProfile(
        slug="ableton",
        name="Ableton Live",
        adapter_strategy="Native Remote Script or AbletonOSC",
        maturity="first_target",
        expected_depth="deep session, clip, device, and browser control",
        capabilities=(
            "read_project_state",
            "transport_control",
            "track_management",
            "clip_or_pattern_editing",
            "midi_note_editing",
            "mixer_control",
            "device_or_plugin_control",
            "browser_or_preset_search",
            "undo_checkpoint",
        ),
        constraints=(
            "Remote Script and AbletonOSC paths have different compatibility profiles.",
            "Arrangement editing may require careful version-specific testing.",
        ),
        docs=(
            "https://help.ableton.com/hc/en-us/articles/209072009-Installing-third-party-remote-scripts",
            "https://github.com/ideoforms/AbletonOSC",
        ),
    ),
    "fl-studio": DawProfile(
        slug="fl-studio",
        name="FL Studio",
        adapter_strategy="Python MIDI scripting bridge",
        maturity="planned",
        expected_depth="good transport, mixer, channel, pattern, and playlist control",
        capabilities=(
            "read_project_state",
            "transport_control",
            "track_management",
            "clip_or_pattern_editing",
            "midi_note_editing",
            "mixer_control",
            "device_or_plugin_control",
            "undo_checkpoint",
        ),
        constraints=(
            "MIDI scripting is event-driven and controller-oriented.",
            "Adapter should avoid long-running threads inside FL Studio scripting.",
        ),
        docs=(
            "https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm",
        ),
    ),
    "reaper": DawProfile(
        slug="reaper",
        name="REAPER",
        adapter_strategy="ReaScript and/or OSC bridge",
        maturity="planned",
        expected_depth="deep project control with strong scripting support",
        capabilities=(
            "read_project_state",
            "transport_control",
            "track_management",
            "clip_or_pattern_editing",
            "midi_note_editing",
            "mixer_control",
            "device_or_plugin_control",
            "arrangement_editing",
            "undo_checkpoint",
            "export_or_render",
        ),
        constraints=(
            "OSC requires pattern configuration for richer bidirectional control.",
            "ReaScript APIs should be checked against the user's installed REAPER version.",
        ),
        docs=(
            "https://www.reaper.fm/sdk/reascript/",
            "https://www.reaper.fm/sdk/osc/osc.php",
        ),
    ),
    "bitwig": DawProfile(
        slug="bitwig",
        name="Bitwig Studio",
        adapter_strategy="Controller extension API",
        maturity="planned",
        expected_depth="good controller and project integration through extensions",
        capabilities=(
            "read_project_state",
            "transport_control",
            "track_management",
            "clip_or_pattern_editing",
            "midi_note_editing",
            "mixer_control",
            "device_or_plugin_control",
            "browser_or_preset_search",
        ),
        constraints=(
            "Adapter packaging is likely Java/controller-extension based.",
            "Capabilities should follow the extension API rather than UI automation.",
        ),
        docs=("https://www.bitwig.com/stories/controller-integration-in-bitwig-studio-414/",),
    ),
    "cubase-nuendo": DawProfile(
        slug="cubase-nuendo",
        name="Cubase / Nuendo",
        adapter_strategy="JavaScript MIDI Remote API script",
        maturity="research",
        expected_depth="controller-style mapping and workflow control",
        capabilities=(
            "transport_control",
            "mixer_control",
            "device_or_plugin_control",
            "undo_checkpoint",
        ),
        constraints=(
            "MIDI Remote API is primarily for controller mediation.",
            "Broad project editing may need additional integration surfaces.",
        ),
        docs=("https://steinbergmedia.github.io/midiremote_api_doc/",),
    ),
    "logic-pro": DawProfile(
        slug="logic-pro",
        name="Logic Pro",
        adapter_strategy="Control surface, MIDI, and safe macOS automation",
        maturity="research",
        expected_depth="workflow and control-surface operations first",
        capabilities=(
            "transport_control",
            "mixer_control",
            "device_or_plugin_control",
        ),
        constraints=(
            "Avoid brittle UI automation for destructive project edits.",
            "Public automation surfaces are less DAW-agent friendly than REAPER or Ableton.",
        ),
        docs=("https://support.apple.com/guide/logicpro/welcome/mac",),
    ),
    "studio-one": DawProfile(
        slug="studio-one",
        name="Studio One",
        adapter_strategy="MIDI and control-surface adapter",
        maturity="research",
        expected_depth="workflow and control-surface operations first",
        capabilities=(
            "transport_control",
            "mixer_control",
            "device_or_plugin_control",
        ),
        constraints=(
            "Needs a stable public automation surface before deep editing is promised.",
        ),
    ),
    "pro-tools": DawProfile(
        slug="pro-tools",
        name="Pro Tools",
        adapter_strategy="HUI/EUCON-style control where viable",
        maturity="research",
        expected_depth="conservative transport and mix control first",
        capabilities=(
            "transport_control",
            "mixer_control",
        ),
        constraints=(
            "Deep control may depend on proprietary or licensed surfaces.",
            "Adapter should be conservative about claims and compatibility.",
        ),
    ),
}

SUPPORTED_DAW_SLUGS = tuple(SUPPORTED_DAWS)


def get_daw_profile(slug: str) -> DawProfile:
    """Return the profile for a supported DAW slug."""

    return SUPPORTED_DAWS[normalize_daw_slug(slug)]


def list_daw_profiles() -> list[DawProfile]:
    """Return all known DAW profiles."""

    return [SUPPORTED_DAWS[slug] for slug in SUPPORTED_DAW_SLUGS]


def normalize_daw_slug(value: str) -> str:
    """Normalize a user-provided DAW name into a target slug."""

    slug = value.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "ableton-live": "ableton",
        "live": "ableton",
        "fl": "fl-studio",
        "flstudio": "fl-studio",
        "reaper-fm": "reaper",
        "bitwig-studio": "bitwig",
        "cubase": "cubase-nuendo",
        "nuendo": "cubase-nuendo",
        "logic": "logic-pro",
        "logicpro": "logic-pro",
        "studioone": "studio-one",
        "pt": "pro-tools",
        "protools": "pro-tools",
    }
    slug = aliases.get(slug, slug)
    if slug not in SUPPORTED_DAWS:
        supported = ", ".join(SUPPORTED_DAW_SLUGS)
        raise ValueError(f"unsupported DAW target '{value}'. Supported targets: {supported}")
    return slug
