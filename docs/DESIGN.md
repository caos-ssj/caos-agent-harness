# Design

The visual decisions of the desktop app, as the owner took them (2026-11-13 and 2026-11-14). This file is the single reference:
when a screen and this file disagree, the file wins or the file is changed first. Tokens live in `web/src/theme.css`; shared
pieces in `web/src/base.css`; screens in `web/src/views.css`, `run.css`, `stations.css`.

## The world

A control room at night, built for work. **Black is the ground.** **Bone-beige is for reading.** **Copper is for acting.**
Science-fiction structure (glass panels, an edge of light, a signal that moves) carries the innovation; the colours and the
blackletter name carry the house.

- Dark only. No light theme.
- Density: balanced. Body 15 px, tables 13.5 px.
- Light and motion mean something: a thing glows or moves because an agent is working or because it needs you.

## Colour

| Role | Token | Value | Use |
|---|---|---|---|
| Ground | `--ground` | `#030303` | The page. Nothing lighter behind panels except the two lights below |
| Panel | `--fill-top` → `--fill-bot` | `#131210` → `#0A0908` | Glass, as an opaque gradient |
| Raised | `--card-2`, `--card-3` | `#121110`, `#1B1917` | Wells, hover, selected |
| Hairline | `--edge`, `--edge-2` | bone at 9 % and 17 % | Every ordinary border. Not copper |
| Read | `--ink`, `--ink-2`, `--ink-3` | `#F3EFE8`, `#C9C2B6`, `#958E83` | Text. `--ink-3` is the floor (≥ 4.5 : 1 on panels) |
| Emphasis | `--champan` | `#EBD3BB` | Headings of note, big figures, the active tab's text |
| Act | `--copper` | `#DDA36A` | The one primary button per screen, selection, focus ring, the edge of light |
| Pass / Fail / Waits for you / Live | `--pass` `--fail` `--wait` `--live` | green, red, amber, blue | One meaning each, everywhere |
| Families | `--fam-claude` `--fam-gemini` `--fam-codex` `--fam-opencode` `--fam-local` `--fam-api` | violet, blue, pink, cyan, bone, copper | The agent's emblem, its station light, its tag |

Two lights only:

1. **Work light.** While an agent runs, the room behind the panels takes its family colour, clearly (visible across the top
   third of the screen). It fades back when nobody works.
2. **Console glow.** A very faint warm glow behind the conversation (`--feed-glow: 0.07`). Never strong enough to tint text.

## Edge of light

Only on what matters: the Console, the stations, the composer, the open task, the active panel. Everything else has a hairline.
The edge is copper at rest and the family's colour on a station that is working.

Hover on a card, row or station: the border gains light and a soft reflection follows the cursor across the surface
(`--mx`, `--my` set by one pointer listener; a radial highlight at 6 % opacity). No lift, no movement of the element.

## Shape

Panels 12 px. Controls 8 px. Status capsules and the active tab are fully round. Three radii, no others.

## Type

| Use | Face | Size / weight |
|---|---|---|
| Page title | IBM Plex Sans | 30 px / 600, tracking −0.02em |
| Section label, table header | JetBrains Mono, uppercase | 12 px / 600, tracking 0.09em, `--ink-2` |
| Body | IBM Plex Sans | 15 px / 400 |
| Data, code, paths | JetBrains Mono | 13 px, tabular numerals, slashed zero |
| Big figure (instrument) | JetBrains Mono | 38 px / 600, tracking −0.02em |
| The name | UnifrakturMaguntia | 30 px, only the word "caos" |

No serif anywhere.

## Chrome

- **Header.** Emblem (28 px, copper, a faint glow behind it) and the name with more presence. Tabs Run · Board · Team · System:
  the active one is a lit glass capsule with an edge of light; the others are plain text with their icon.
- **Sidebar.** Collapsed by default; opens from the header button. When collapsed it is gone, not an icon rail.
- **Status bar** (bottom). Live: current branch, agents working now (with their emblems), the last verification result and the
  time. Replaces the static text.
- **Boot.** On black: the emblem draws stroke by stroke, the name appears, the stations light one by one, under two seconds;
  then the app. Skipped with reduced motion or the "focus" motion preference.

## Controls

- **Buttons.** One primary per screen: solid copper, dark text. Everything else is glass with a hairline that lights on hover.
  Amber, green and red buttons keep their meaning (waits for you, accept, destructive).
- **Status capsule.** Round capsule with a drawn status glyph and the text, tinted by state. Replaces the boxed chips.
- **Icons.** One drawn set, 24 grid, 1.6 stroke, square caps: the agent emblems and step glyphs that exist, plus the common
  actions redrawn in the same hand (search, close, copy, settings, collapse, send, refresh, branch, play, undo, plus, check,
  warning, folder, file, diff, external link, eye, pencil, trash, lock, key, download, upload, more).

## Run

Left: the conversation, full height. Right column: since your last visit, the stations, then the verification tabs.

- **Console bar.** Mode (Plan · Act · Orchestrate) and engine in view; skill, worktree, pipeline and inspector in one options
  menu.
- **Chat, two sides.** Your messages on the right in a faint beige bubble. Each agent's answer on the left, with its emblem,
  name and family colour above the bubble, the time, and its steps (read, edited, ran) as a fold under the text.
- **Empty console.** Three mission cards found in the repository by code (`/api/missions`): what, the file and line, a button
  to launch. No emblem, no instructions.
- **Composer.** The protagonist: taller, an edge of copper light on focus, a solid copper send button. No repeated mode or
  engine chips.
- **Stations.** Taller and alive: larger emblem, the signal across the full width and higher, state clearly readable.
  The signal is an oscilloscope trace with a glow in the family's colour and a fading trail while the agent works; a still
  line with one mark for the last call otherwise.
- **Instruments** (activity, reviewers, work by tier) live inside the Reviewers and Costs tabs, not under the stations.
- **A review round.** Author → reviewer with emblems, the status capsule, and one **segmented bar** of four parts (review, merge,
  tests, branch) filled with the colour of each result; names under the segments; the detail on hover and on open.

## Board

- Counters (wait for you, running, pending, with a person) in one strip across the top, as big instrument figures.
- Rows are taller: a mark in the state's colour at the left edge, the agent's emblem, the title large, and under it one fine
  line with number, state, agent and the mini track of its review round. Activity is a narrow column at the right.

## Team and System

- **Skills list.** Each skill: its own glyph, its name, and at the right its first-attempt score with a small bar.
- **Engines.** Each engine is a glass card with its family emblem, a state dot (ready, key missing, not measured), its measured
  precision as a gauge, and its actions. Same language as the stations.
- **Metrics.** Balanced: indicators in one compact strip, then the trend and the tier matrix side by side with equal weight.
  Charts by kind of data: oscilloscope for continuous values, bars for counts, a dot matrix for outcomes.

## Sound

Three short synthesised tones: a change landed, a test failed or a change was rejected, something waits for you. On by
default, off in Preferences.

## Never

- A number that was not measured, or a signal that moves when nothing runs.
- A second primary button on one screen. Copper as decoration.
- Blur as a material (no `backdrop-filter`). Gradient text. A coloured side stripe wider than 1 px, except the state mark of
  a Board row, which is the row's status and is 3 px by design.
