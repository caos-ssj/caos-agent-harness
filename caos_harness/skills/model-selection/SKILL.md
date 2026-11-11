---
name: model-selection
description: Choosing which model runs a task, or routing a request to a local model. Use before calling any model from a workflow, script or agent step.
---

# Model selection

Choose by **what a wrong answer costs**, from measurements. The table is produced by the repository:

```
make route        # each cost-of-error tier and the measured system it gets
```

## Rules
- Take the system `make route` gives for the task's tier. `human review` is an answer: the task goes to a person.
- A model is eligible only for tasks of a kind it was measured on. A new kind of task needs its own golden set and benchmark first (`make benchmark MODELS="..."`).
- Small models classify and extract. Reasoning, comparing and deciding go to the larger measured model, or to a person.
- Ask for structured output twice: `"format": "json"` in the request and the schema in the system prompt. Temperature 0 for classification and extraction.
- A model's self-reported confidence is one signal. Pair it with an independent one (rules, a second model) and escalate when they disagree.

## When a model is added or changed
Re-run the benchmark and `make route`. The new numbers replace the old ones; nothing here needs editing.
