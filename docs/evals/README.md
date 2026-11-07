# Evals

An evals pass reads the transcripts of real sessions where an agent used
abletonian on a musician's set, counts what the tools did, and turns every
miss into an issue. It is the third testing layer in `CONTRIBUTING.md`
seen from the musician's side: not "did the Remote Script do what the code
says" but "did the session need fewer hands on the mouse".

Each pass is one file named by date and the work it covers. A pass records:

- which sessions and which Live, OS and adapter versions;
- counts of tool calls, split into worked, oversized, bridge error, batch
  stopped;
- what went well, so the next change does not break it;
- every limitation, with the transcript evidence and the issue it became;
- what is out of reach of the Live API, so nobody files it twice.

Passes:

- [2026-11-08: Aperol Fritz mix sessions, 2026-11-01 to 11-06](2026-11-08-aperol-fritz-mix-sessions.md)
