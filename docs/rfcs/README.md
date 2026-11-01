# RFCs

An RFC is a short design document for a change that is hard to undo or that
many contributors will build on. Most work does not need one: an issue and a
PR are enough (see `CONTRIBUTING.md`).

## When to write one

- A change to the bridge protocol or `daw.health` capability model.
- A change to the safety model: what needs confirmation, how undo works.
- A new DAW adapter or a new kind of adapter (Max for Live, OSC, ...).
- A new user-facing surface (a panel, MCP Apps, an in-Live UI).
- A refactor that spans the MCP server, the bridge, and the Remote Script.

If you are not sure, open a feature issue and ask.

## How it works

1. Copy `0000-template.md` to `NNNN-short-title.md` using the next free
   number, set **Status: Draft**, and open a PR. Discussion happens on the PR.
2. When a maintainer approves the design, the PR is merged with
   **Status: Accepted**, and a tracking issue is opened and linked in the
   header. The tracking issue holds the task list; implementation PRs link
   to it.
3. While building, add dated notes to **Implementation notes** when the code
   deliberately differs from the design. Do not keep progress checklists in
   the RFC.
4. When the tracking issue closes, set **Status: Implemented**.

Other statuses: **Withdrawn** (the author dropped it), **Rejected** (with a
short note on why), **Superseded by NNNN**. RFCs stay in this one folder
whatever their status, so links never break.

## Index

| RFC | Title | Status |
| --- | --- | --- |
| [0001](0001-ableton-deep-integration-foundation.md) | Ableton deep integration foundation and Drum Rack extraction | Implemented |
| [0002](0002-selected-rack-macro-cockpit.md) | Selected Rack Macro Cockpit | Accepted (read-only slice built) |
