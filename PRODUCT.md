# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
Frontend framework, chosen by the user (2026-11-10); the specific one was delegated: React + TypeScript + Vite, built to static files that the Python standard-library server ships inside the package, so `caos-harness serve` needs no Node at run time.

## Users
First the author, running his own AI agents day to day. Then the CAOS development team, sharing the same board. Later, the public: people who open the repository and evaluate it (confirmed by the user, 2026-11-10).

## Product Purpose
caos-agent-harness runs AI agents in a way that can be checked: a task board that routes work and holds it for review, a policy layer between model and tools, a model router driven by measured results, shared memory over MCP, evaluation gates, a human review queue and one trace format. Success is that the operator can answer, for any task, who got it, what they delivered, why it was accepted or returned, and what it cost.

## Positioning
Every number it shows comes from a command anyone can rerun, and abstaining or sending a task to a person is a first-class result with a reason.

## Operating Context
A project folder with `harness.toml`; agents are commands. The operator adds tasks, runs them, reads deliveries and gives a verdict (`ok`, `redo`, `verify`, `superseded`). The same actions exist in the CLI (`caos-harness`) and in the local dashboard (`caos-harness serve`, loopback only).

## Capabilities and Constraints
- Task lifecycle: pending, sending, sent (delivered or not), discarded; review verdicts ok, redo, verify, superseded. The queue named `person` is the human reviewer's.
- Router tiers (low, medium, high, critical) decide the agent or a person from measured profiles.
- The trace holds identifiers, statuses and reasons, never task text.
- Interface language: English (user, 2026-11-10). No authentication: the server listens on 127.0.0.1 only.
- Undecided: multi-user review with reviewer names; remote access.

## Brand Commitments
CAOS identity as recorded in the brand note of 2026-09-28: "nocturnal, sober". Palette: negro #060607, tinta #101013, borde #26262A, tenue #5C5C5A, gris #93938F, hueso #EDEAE5, champán #EBD3BB, ámbar #C9975C. Three voices: UnifrakturMaguntia for the name only; EB Garamond for the human voice; JetBrains Mono for evidence (figures, commands, paths). One warm element per piece. The CLI carries the same identity (user, 2026-11-10).

Interface decisions (2026-11-11, owner's direction, see docs/DESIGN-REVIEW.md): the dashboard keeps its five views (Console, Board, Providers, Measured, Skills), polished: rounded cards at three radii, soft edges and quiet shadows, readable type (system sans body at 15.5 px, EB Garamond headings, mono only for data and commands), one icon set plus the repository's hairline engravings as the pages' own plates. Amber means "this needs you" in every control and figure; the primary button is bone. Personalisation is density, text size and start view. A workspace menu switches between listed project folders. Sample data is always labelled. The Spanish motto appears once, in the footer.

## Evidence on Hand
Reports under `reports/` (agent eval, benchmarks, mutation), the deterministic demo (`make demo`), and aggregate use of the original board: 115 tasks between 2026-09-29 and 2026-11-09, 86 reviewed. No customers, testimonials or pricing exist; none may be shown.

## Product Principles
1. A number on screen names the command that produced it.
2. Nothing closes without a verdict, and a verdict always has an author's reason.
3. "A person decides" is a result, shown with the same weight as an answer.
4. The task's whole life is one glance: queue, router decision, delivery, review.
5. The CLI and the dashboard say the same thing with the same words.
