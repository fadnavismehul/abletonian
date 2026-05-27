# RFC Index and Process

**Status:** Proposed  
**Created:** 2026-05-23  
**Owner:** Core Team

## Purpose

This folder stores Request for Comments (RFCs) for non-trivial changes in
`abletonian`.

RFCs are lightweight, agent-legible specs that explain what we are changing, why
it matters, how safety is preserved, and how success is verified inside Ableton
or against a fake adapter.

## Lifecycle

- **Proposed**: draft or under review before implementation starts, located in
  `docs/product/rfcs/proposed/`
- **In Progress**: implementation has started, is partially shipped, or the idea
  is being validated against code reality, located in
  `docs/product/rfcs/inprogress/`
- **Implemented**: shipped and verified against acceptance criteria, located in
  `docs/product/rfcs/done/`
- **Parked**: deferred, abandoned, or blocked, located in
  `docs/product/rfcs/parked/`
- **Discarded**: rejected proposal, located in `docs/product/rfcs/discarded/`
- **Superseded**: replaced by a newer RFC, located in
  `docs/product/rfcs/superseded/`

## When an RFC Is Required

RFC is required for non-trivial changes, including:

- new musician-facing workflow or major behavior change,
- new Ableton integration surface,
- bridge protocol change,
- safety or permission model change,
- storage, logging, RTFM/manual-index, or adapter architecture change,
- refactor spanning multiple modules or layers,
- behavior that requires manual Ableton verification.

RFC is optional for typo fixes, narrow docs changes, and small maintenance
updates that do not alter product behavior or architecture.

## Numbering and Naming

- Filename format: `RFC-XXX-short-kebab-title.md`
- `XXX` is zero-padded (`001`, `002`, ...)
- Keep one RFC per decision scope.
- Use `RFC-000-template.md` as the starting scaffold for new RFCs.

## Required RFC Metadata

Every RFC must include:

- `Status`
- `Created`
- `Owner`
- `Implementation Status`

## RFC-to-Code Enforcement

Agents and maintainers should treat RFCs as implementation-tracking records, not
static proposals. For any non-trivial code change that implements or changes an
RFC:

1. Identify the relevant RFC before editing code.
2. Move the RFC to `docs/product/rfcs/inprogress/` when implementation begins or
   when only part of the RFC is shipped.
3. Update the RFC in the same commit or PR with implementation status, touched
   modules, verification results, open follow-ups, and accepted deviations.
4. Add a commit footer so history can be searched by RFC:

   ```text
   RFC: RFC-XXX
   ```

5. Move the RFC to `done/` only after acceptance criteria are satisfied or
   explicitly amended with rationale.

These rules are enforced for agents by `docs/product/rfcs/AGENTS.md`.

## RFC Registry

| RFC | Status | Location | Summary |
| --- | --- | --- | --- |
| RFC-001 | In Progress | `docs/product/rfcs/inprogress/RFC-001-ableton-deep-integration-foundation.md` | Establish the hybrid Ableton integration foundation and first workflow wedge. |
