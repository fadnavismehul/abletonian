# Contributing to abletonian

Thanks for helping. abletonian edits people's music, so the bar is
"careful and verifiable" more than "fast". This guide covers how work flows,
how to set up, and how to test without and with Ableton Live.

If you work with a coding agent, point it at `AGENTS.md`. It holds the
commands, invariants, and gotchas, and humans should read it too.

## How work flows

Pick the lightest path that fits:

| Change | Path |
| --- | --- |
| Typo, docs fix, small bug with an obvious fix | Open a PR directly. |
| Bug | Open a bug issue (include your Live version and OS), then a PR that links it. |
| New tool, workflow, or behaviour change | Open a feature issue first and wait for a maintainer to agree on the shape. PRs for features nobody discussed may be closed without review. |
| Bridge protocol, safety model, new DAW adapter, new UI surface, or anything spanning several layers | Write an RFC (see [`docs/rfcs/`](docs/rfcs/README.md)), then build it in small PRs that link the RFC's tracking issue. |

## Issues

- **Kind** is a GitHub issue type: **Bug**, **Feature**, or **Task**. The
  issue forms set it for you.
- **Labels** say where and in what state. Areas are `area: remote-script`,
  `area: mcp-server`, `area: cockpit`, `area: adapters`, `area: manual`,
  `area: docs`, and `area: ci`. Status labels are `needs-triage`,
  `needs-live-validation`, `blocked`, and `needs-rfc`. The full list, with
  descriptions, is `.github/labels.yml`. Change labels by editing that file;
  a workflow syncs it to GitHub.
- **Big work is split into sub-issues.** A feature or RFC tracking issue
  holds the plan, and each sub-issue is one PR's worth of work.
- **Claim before you start.** Comment on the issue so two people (or agents)
  do not build the same thing. A maintainer will assign it to you.
- `good first issue` is scoped to be doable without deep Live knowledge.
  `needs-live-validation` needs someone with Ableton Live to run something
  and report back, and needs no code at all.

## Setup

```bash
git clone https://github.com/fadnavismehul/abletonian.git
cd abletonian
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Python 3.10 or newer. You do not need Ableton Live to work on most of the
code.

## Testing

There are three layers. CI runs the first two.

1. **Unit tests with fakes**: `tests/`, run with `pytest`. Live is replaced
   by small objects shaped like the Live Object Model, and workflows run
   against `FakeAbletonAdapter`.
2. **Real set fixtures**: `testing/First Light Project/` holds real `.als`
   files parsed by `tests/test_als_integration.py`. Do not save over them.
3. **Live validation**: run the Remote Script in Ableton Live and record what
   happened. See [`docs/engineering/live-validation.md`](docs/engineering/live-validation.md)
   and the "Live validation report" issue form. Anything under
   `remote_scripts/` is unverified until this layer has run.

Lint with `.venv/bin/ruff check src tests remote_scripts scripts`.

## Pull requests

- Keep each PR to one change. Several small PRs review faster than one large
  one.
- Fill in the PR template: what changed, how you tested it, and whether it
  ran in Live (and which version).
- Update docs that your change makes wrong in the same PR.
- New MCP tools need a musician-facing reason. Raw bridge passthrough tools
  will not be merged.
- Mutating features need an undo or backout story
  ([`docs/engineering/robustness-and-safety.md`](docs/engineering/robustness-and-safety.md)).

Commit messages use [Conventional Commits](https://www.conventionalcommits.org/)
prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`). If a commit implements
part of an RFC, mention it in the body (for example `Part of RFC 0002`).

## AI-assisted contributions

Welcome, with disclosure and a human who understands the change. Read
[`AI_POLICY.md`](AI_POLICY.md).

## Conduct and security

Be kind and assume good faith. See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
Report security issues privately as described in [`SECURITY.md`](SECURITY.md),
not in public issues.

## License

By contributing you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
