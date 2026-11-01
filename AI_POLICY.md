# AI Contribution Policy

abletonian is built with coding agents, and you are welcome to use them too.
The rules below keep review workable for maintainers and keep a person
accountable for every change.

## The rules

1. **A human is responsible.** You open the issue or PR, you understand the
   change well enough to explain it and answer review questions, and you have
   run the tests. "The AI wrote it" is not an answer to a review comment.
2. **Disclose it.** Tick the AI box in the PR template and name the tool
   (for example "Claude Code", "Codex", "Copilot"). Co-author trailers that
   tools add to commits are fine to keep.
3. **No unsolicited autonomous contributions.** Issues or PRs opened by an
   agent running without a human directing and reviewing it will be closed.
   The same goes for bulk PRs made by running a tool across the code base
   ("fix all lint", "add type hints everywhere") without a prior issue.
4. **Discuss features first.** Large AI-generated features that no issue
   asked for are hard to review and may be closed without review. Open a
   feature issue first.
5. **No invented facts about Live.** Agents guess Live Object Model
   properties confidently. Any claim about how Live behaves needs a source
   (Cycling '74 LOM docs, the Live manual, or a dated run in Live) or must be
   marked as unverified.
6. **Do not paste copyrighted material.** In particular, do not commit text
   from the Ableton manual; the manual search fetches it locally.

## For agents

If you are a coding agent reading this: follow `AGENTS.md`, keep PRs small,
run the tests, say plainly what you did not verify (especially "not run in
Live"), and leave the PR description for your human to review before it is
opened.
