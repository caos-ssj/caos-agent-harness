---
name: context-engineering
description: Structuring agent prompts, context windows, session state and tool context so small and large models stay grounded.
---

# Context Engineering

## Context Budget
1. Load only the files, diffs and symbols needed for the current task rather than dumping whole directories.
2. Put constraints, schema expectations and verification commands concisely at the top of the prompt.
3. Ask targeted clarifying questions when requirements conflict or target files remain ambiguous.

## State Hygiene
- Separate global preferences and credentials from project-scoped state and session traces.
- Keep hand-off summaries factual and grounded in observed command outputs.
