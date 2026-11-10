# Benchmark de modelos locales — 2026-11-04-llama3.2_1b-llama3.2_3b

Conjunto v2 (74 casos sintéticos; 25 en `test`, reservados). Intervalos de Wilson 95 %.

| Sistema | Partición | n responde | Cobertura | Precisión (IC95) | ECE | p50 s | p95 s | Rechazos |
|---|---|---|---|---|---|---|---|---|
| `llama3.2:1b` | test | 0/23 | 0.0 | 0.0 (0.0, 0.0) | 0.0 | 1.505 | 1.665 | 2/2 |
| `llama3.2:1b+rules` | test | 0/23 | 0.0 | 0.0 (0.0, 0.0) | 0.0 | 1.476 | 1.665 | 2/2 |
| `llama3.2:1b` | all | 0/66 | 0.0 | 0.0 (0.0, 0.0) | 0.0 | 1.294 | 1.613 | 8/8 |
| `llama3.2:1b+rules` | all | 0/66 | 0.0 | 0.0 (0.0, 0.0) | 0.0 | 1.384 | 1.59 | 8/8 |
| `llama3.2:3b` | test | 21/23 | 0.913 | 0.952 (0.773, 0.992) | 0.081 | 1.483 | 1.901 | 2/2 |
| `llama3.2:3b+rules` | test | 20/23 | 0.87 | 1.0 (0.839, 1.0) | 0.125 | 1.627 | 1.798 | 2/2 |
| `llama3.2:3b` | all | 60/66 | 0.909 | 0.883 (0.778, 0.942) | 0.01 | 1.41 | 1.754 | 8/8 |
| `llama3.2:3b+rules` | all | 53/66 | 0.803 | 0.962 (0.872, 0.99) | 0.085 | 1.457 | 1.739 | 8/8 |
