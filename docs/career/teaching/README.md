# Teaching-oriented collaboration

> **Status: current collaboration contract. Protocol version: `1`.**
> `AGENTS.md` makes this protocol mandatory for non-trivial implementation and
> validation work.

Project delivery and guided learning happen in the same bounded task. Prefer
clear Chinese explanations while retaining exact English terms, identifiers,
commands, metrics, and file names used in industry and in the repository.

| Module | Purpose |
| --- | --- |
| [Step protocol](STEP_PROTOCOL.md) | What to explain before, during, and after a non-trivial step |
| [Evidence discipline](EVIDENCE_DISCIPLINE.md) | How learning and resume material remain honest and tracker-safe |
| [Interview translation](INTERVIEW_TRANSLATION.md) | How durable engineering results become defensible interview answers |

## Project-specific boundaries

- The MCP server and existing Runner are the sole desktop dispatch path.
- Model output is untrusted data, never authority.
- Unknown side-effect outcomes are never automatically replayed.
- Refs never silently fall back to coordinates.
- Safe automatic Full Cycle export remains separate from explicit-consent rich
  capture.
- Live provider, desktop, application, human, and release evidence are distinct.
- Possible user mouse, keyboard, or focus intervention invalidates a supervised
  desktop attempt until re-observation and rerun establish an attributable result.

Teaching never broadens authority. A missing account, unavailable device,
required human judgment, ambiguous tracker item, or unresolved PR state remains
a blocker even when explaining the topic would be educational.
