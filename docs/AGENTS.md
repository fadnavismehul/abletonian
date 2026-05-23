# AGENTS.md

## Documentation Scope

This file applies to everything under `docs/`. Documentation is part of the
product contract for `abletonian`: keep it accurate, navigable, and tied to the
decision record or implementation surface it explains.

## Documentation Map

- `docs/product/`: product vision, positioning, milestones, and RFCs.
- `docs/product/rfcs/`: decision records for non-trivial product,
  architecture, workflow, integration, safety, or adapter changes.
- `docs/design/`: interaction principles, user experience constraints, and
  design philosophy.
- `docs/engineering/`: architecture notes, integration references, safety
  requirements, and development guides.
- Root-level docs such as `docs/architecture.md`, `docs/daw-targets.md`, and
  `docs/strategic-directions.md` are early exploration docs. Prefer adding
  durable new material under the product/design/engineering taxonomy.

## Editing Rules

- Prefer updating existing docs over creating near-duplicate pages.
- Keep product docs outcome-oriented and musician-facing.
- Keep design docs explicit about interaction, trust, control, and workflow
  expectations.
- Keep engineering docs explicit about APIs, version constraints, safety
  invariants, test strategy, and references.
- If a code change makes a doc inaccurate, update the doc in the same change.
- For RFC changes, follow `docs/product/rfcs/AGENTS.md`.

## Required Cross-Checks

Before finishing docs changes:

1. Check links and paths touched by the change.
2. Ensure RFC metadata and lifecycle folders agree.
3. Ensure engineering claims that depend on Ableton, Max for Live, or third-party
   APIs include source references.
