# Security Policy

## Reporting a vulnerability

Please report security issues privately through GitHub's
[private vulnerability reporting](https://github.com/fadnavismehul/abletonian/security/advisories/new),
not in public issues or PRs. We aim to acknowledge reports within a week.

## What is in scope

abletonian runs on your machine with access to your open Live Set:

- The Remote Script listens on `127.0.0.1:9877` with no authentication. Any
  local process can send it commands. Issues that let a non-local client
  reach it, or that let it read or write files outside the Live Set, are in
  scope.
- The MCP server passes model-generated arguments to the bridge. Ways to
  make it perform destructive Live operations without the documented
  confirmation are in scope.
- Supply-chain issues in how the Remote Script is installed into the User
  Library.

Prompt injection through track, clip, or device names that leads to
unconfirmed destructive actions is in scope. Model output that is merely
wrong is not a security issue; open a normal bug.
