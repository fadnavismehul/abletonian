# Abletonian Documentation

`abletonian` is a FOSS DAW agent framework and MCP server. Ableton Live is the
first target. New here? Read the top-level `README.md`, then `CONTRIBUTING.md`.
Coding agents start at `AGENTS.md`.

## Product and design

- [Product Vision](product/vision.md): who it is for and what it should feel like.
- [Design Philosophy](design/philosophy.md): trust, control, and workflow principles.

## Engineering

- [Live Set Control](engineering/live-control.md): setup, MCP tools, and the Live validation log.
- [Live Validation](engineering/live-validation.md): how to check Remote Script changes in Live.
- [Robustness and Safety](engineering/robustness-and-safety.md): operation classes and invariants.
- [Ableton Integration Options](engineering/integration-options.md): Remote Scripts, Max for Live, OSC.

## Evals

- [Evals passes](evals/README.md): real-session transcripts read for what the tools did and
  did not manage. Latest: [Aperol Fritz mix sessions, November 2026](evals/2026-11-08-aperol-fritz-mix-sessions.md).

## Decisions

- [RFCs](rfcs/README.md): designs for protocol, safety, adapter, and surface changes.

## Research

- [Landscape and direction review, November 2026](research/2026-11-landscape-and-direction-review.md):
  the Ableton Extensions SDK, Max for Live, competing DAW MCP servers, and what
  they mean for abletonian's architecture and roadmap.

## Background

- [`exploration/`](exploration/): early architecture, DAW target, strategy, and vision notes.
  Useful context, not a commitment.
- [`ableton-survey/`](ableton-survey/): the 2026 Ableton Live and AI user survey.
- [`archive/plans/`](archive/plans/): step-by-step plans agents followed for
  RFC 0001. Kept for history; new working plans belong in PR descriptions.
