# Improving a skill from evidence

A skill is the working instructions an agent loads for a kind of task. This is the contract for changing one because of what the
board recorded, without a paid model reading traces and without a change staying on anyone's say-so.

What exists, with tests: `caos_harness/skill_eval.py` (`evidence`, `redo_notes`, `record_change`, `history`, `gate`,
`validate_proposal`, `pack`, `propose`, `start_trial`, `trial_status`, `close_trial`, `overview`), the dashboard endpoints under
`/api/skills/` and the evidence panel in Team › Skills. What is to build is marked **to build**.

## The loop

```
board + trace ──code──▶ pack ──reader (free/cheap agent)──▶ proposal ──code──▶ valid?
     ▲                                                                          │ yes
     │                                                              another agent reviews, a person approves
     │                                                                          ▼
  gate: promote | reject | insufficient ◀── trial: N decided tasks ◀── candidate text, project-local
```

1. **Pack** (code, no model). For one skill: its `evidence` row, every `redo_notes` entry, and for the returned tasks the first
   1,500 characters of the delivery that was returned. Hard budget: 24,000 characters. A pack never contains task text from
   another skill, files, or anything outside the board.
   Exists: `pack(board, skill, budget=24_000) -> str` (numbers, return notes and what was asked; the returned delivery itself is
   not kept by the board, so it is not in the pack).
2. **Reader.** A free or cheap agent (never the paid one) receives the pack and the current `SKILL.md` and answers with one
   proposal as JSON. It is asked for the single change that would have prevented the most returns.
   Exists: `propose(project, skill_name, reader=None, factory=None) -> dict` (uses `orchestrator.ask`, read-only; no model is
   called without return notes from at least two tasks).
3. **Validation** (code, exists: `validate_proposal`). A proposal is discarded unless every evidence quote is a literal part of a
   recorded return note, at least two different returned tasks back it, `base_sha` is the current text, and the anchor is a real
   line of the skill.
4. **Cross-review and approval.** A different agent (`cycle.pick_verifier`) is asked to argue against the proposal; then a person
   approves the trial. Skills steer every later task, so this step is never automatic.
   Today the person approves by pressing *Start trial* on a validated proposal. **To build:** the cross-review before it.
5. **Trial.** The candidate text is written to `.harness/skills/<name>/SKILL.md` (the project-local override; the packaged skill
   is not touched) and `record_change` marks the moment. One open trial per skill.
   Exists: `start_trial(project, proposal) -> dict`, `open_trials(root) -> dict`. A line ending in `[fixed]` cannot be replaced
   or removed.
6. **Gate** (exists: `gate`). After at least 20 decided tasks on each side: `promote` keeps the text, `reject` restores the
   previous text and records that change too, `insufficient` keeps collecting. Decisions use the bounds of the 95 % interval.
   Exists: `close_trial(project, skill_name, force=None) -> dict`; a restore that does not reproduce the recorded `sha` raises
   and leaves the trial open. `force` is the person deciding with less evidence than the gate asks for, and is recorded as such.

## The proposal

```json
{
  "skill": "coder",
  "base_sha": "3f2a9c1e5b7d4a10",
  "problem": "Deliveries are returned for lacking the output of the test run.",
  "evidence": [
    {"task": 41, "quote": "no evidence of the run"},
    {"task": 57, "quote": "says the tests pass but shows no output"}
  ],
  "change": {"kind": "add_rule", "anchor": null, "text": "End every delivery with the exact test command and its last ten lines of output."},
  "expected": "Returns that mention missing evidence of the run stop."
}
```

`kind` is `add_rule`, `replace_rule` or `remove_rule`; `anchor` is a literal line of the current skill and is required for the last
two; `text` is one rule of at most 600 characters. A proposal is one change: several problems are several proposals, tried one
at a time, because two changes in one trial cannot be told apart.

## What is compared

| Question | Function | Unit |
|---|---|---|
| Which skill passes review at the first attempt? | `evidence(board)` | decided tasks per skill |
| Does it depend on the agent? | `evidence(board, by_agent=True)` | decided tasks per skill and agent |
| Did a change help? | `history(board, root, skill)` then `gate` | decided tasks per version, by period |
| Why is it returned? | `redo_notes(board, skill)` | reviewer notes, literal |

Comparing by period assumes the mix of tasks did not change with the text. A concurrent A/B removes that assumption: it needs the
skill's `sha` stored on each task when it is queued and a rule to assign versions. **To build:** column `skill_sha` on the board,
filled in `Board.add`; `history` then groups by it instead of by period.

## Limits

- First-pass acceptance measures what the reviewer returns, not what is true. A lenient reviewer raises every skill.
- With fewer than 20 decided tasks per side the gate says `insufficient`, by design. A skill used twice a week takes months.
- A free reader may log what it receives: packs are built from the board of the project they belong to, so a project with
  client work needs a private reader.
