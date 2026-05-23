# AGENTS.md

## RFC Scope

This file applies to all RFC files under `docs/product/rfcs/`. RFCs are not just
proposals; they are the durable contract between product intent, implementation,
and verification.

## Lifecycle Folders

Use exactly one lifecycle folder for each non-template RFC:

- `proposed/`: idea is being explored or reviewed, and implementation has not
  started.
- `inprogress/`: implementation has started, the RFC is partially shipped, or
  code reality is actively shaping the proposal.
- `done/`: implementation satisfies the acceptance criteria and records what
  shipped.
- `parked/`: work is intentionally deferred, abandoned, or blocked.
- `discarded/`: proposal was rejected and should not be revived without a new
  RFC.
- `superseded/`: RFC has been replaced by a newer RFC.

Move RFCs between folders when lifecycle changes. Do not leave partially
implemented RFCs in `done/`.

## Implementation Coupling Rules

For any code change that implements, changes, or intentionally deviates from an
RFC:

1. Identify the RFC before editing code. If no RFC exists and the change is
   non-trivial, create or update one first.
2. Move the RFC to `inprogress/` when implementation begins or when only part of
   the acceptance criteria will be delivered.
3. Update the RFC in the same commit or PR as the code change with:
   - implementation status,
   - changed files or modules,
   - verification commands/results,
   - open follow-ups or acceptance criteria not yet satisfied,
   - decision changes from the original proposal.
4. Add an RFC tag to the commit message footer for targeted tracking:

   ```text
   RFC: RFC-XXX
   ```

5. If a code change deliberately diverges from the RFC, add a dated note under
   the RFC implementation log explaining why.
6. Only move an RFC to `done/` when all required acceptance criteria are met or
   explicitly amended with rationale.

## Required RFC Sections

New and materially updated RFCs should include these sections from
`RFC-000-template.md`:

- Goal
- Problem Statement
- Scope
- Proposal
- Alternatives Considered
- Implementation Plan
- Acceptance Criteria
- Risks and Mitigations
- Rollout and Backout
- Open Questions
- Implementation Tracking

## Registry Rules

- Update `docs/product/rfcs/README.md` when adding, moving, renaming, parking,
  discarding, superseding, or completing an RFC.
- Registry location must match the actual folder.
- Registry status must match the RFC metadata and lifecycle folder.
- If two RFCs use the same number, reconcile before adding more RFCs.
