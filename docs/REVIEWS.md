# Independent reviews

Before each delivery the work is read by agents that did not write it. They run read-only (plan mode, no edit rights) and
their answers are treated as drafts: every finding is checked against the code before anything changes. What each one said
and what was done with it.

## The terminal interface (2026-11-11)

**OpenCode** (`opencode run --agent plan`, free model) compared the first board-style TUI with OpenCode's own loop and found
that the central loop was missing: a conversation, in-screen approval of shell commands, a model and mode selector, sessions
as conversations, and an Esc that cuts. All five were built (`caos_harness/chat.py`, `tui.py`). A second pass found six
defects, all fixed: a finished exchange cleared the run of a newer one, a stopped turn was overwritten when the task
finished, an expired approval stayed on screen, the history dropped a real turn when a refusal note was added, attached files
were read whole before the 20 KB cut, and chat and board sessions shared a folder. What still differs from OpenCode: no token
streaming (the local engine answers whole), one shell tool, a binary permission per command, no kill of a running command.

**Antigravity / agy** (`agy --mode plan`) reviewed the screens drawn as text. Applied: amber was spent on "you" (it now means
only "needs the operator"), the transcript was bottom-anchored with a dead top (now top-down), the modal had no frame and did not
mask the screen (now a closed, opaque box), and the footer showed every key always (now contextual). Offered, applied in part:
a personalisation layer (skin, density, hints, side panel in `~/.config/caos-harness/tui.json`).

**Codex / ChatGPT** (`codex exec -s read-only`) judged the idea and both surfaces. It said the central idea (route by a measured
lower bound, or a person) does not read in 30 seconds. Applied: a one-sentence flow under the Board title; the new-task form
defaults to the router (by cost of error) when it routes to an agent; interval bars now draw the real 95 % interval (lower to upper
end, both stored in the report) with `n` and a plain statement that the figures describe a synthetic set on this CPU; the row
shows the router's recorded reason ("lower bound 91.0 % ≥ 90 %"); every verdict needs a reason (one-click quick reasons); the
terminal shows a waiting command in full, with its folder and a note that it runs with your permissions; failures stopped
using amber and the `ice` skin was dropped; "clean or not a git folder" became two different messages; the wording "at least … sure"
became "lower bound". Not applied: dimming the critical line in the chart (it marks the cost of error that goes to a person).

## The five-view dashboard (2026-11-11)

The impeccable finish reviewer read the screenshots and the source twice. First round, applied: tabs that did not fit at 1024 px, a
chart unreadable on a phone, a kicker above a heading, amber used on decoration, text under 13 px, and a spec that contradicted the
shipped design. Second round (Board tools), applied: a moved task claimed the router had chosen its new queue, a stale
instruction in the first-run copy, buttons inside a heading, a drop bar that overflowed, an error toast when dropping a task on its
own queue, wrong empty-state copy for a search, a non-string queue giving a server error, and unvalidated saved views.

## The idea from T3 Code

A video tour of T3 Code (a desktop app that puts Claude Code, Codex and others under one chat) was used as a reference for
logic, not look: an attention tray (here: the *Needs you* count and card), a queue for prompts typed while an agent works
(built in the terminal), inline comments on a delivery that gather into one return (built in the dashboard), `/` commands with
skills, detecting installed agent CLIs. What T3 Code lacks and this harness keeps: the step-by-step trace, a mandatory verdict, the
router by measured reliability, local models as first-class, and figures that are real.
