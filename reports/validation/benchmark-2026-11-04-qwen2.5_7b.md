# Benchmark de modelos locales — 2026-11-04

Conjunto v2 (74 casos sintéticos; 25 en `test`, reservados). Intervalos de Wilson 95 %.

| Sistema | Partición | n responde | Cobertura | Precisión (IC95) | ECE | p50 s | p95 s | Rechazos |
|---|---|---|---|---|---|---|---|---|
| `qwen2.5:7b` | test | 22/23 | 0.957 | 1.0 (0.851, 1.0) | 0.105 | 2.942 | 3.827 | 2/2 |
| `qwen2.5:7b+rules` | test | 22/23 | 0.957 | 1.0 (0.851, 1.0) | 0.105 | 3.008 | 3.427 | 2/2 |
| `qwen2.5:7b` | all | 62/66 | 0.939 | 0.968 (0.89, 0.991) | 0.085 | 2.895 | 3.517 | 8/8 |
| `qwen2.5:7b+rules` | all | 59/66 | 0.894 | 0.983 (0.91, 0.997) | 0.073 | 2.919 | 3.501 | 8/8 |
