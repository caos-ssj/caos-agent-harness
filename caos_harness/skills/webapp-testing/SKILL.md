---
name: webapp-testing
description: End-to-end verification of local web apps using real browser automation, DOM layout assertions and network/console checks.
---

# Webapp Testing

## Core Checks
1. Start the app cleanly against an isolated temp or sandbox workspace; never mutate production state.
2. Assert zero `console.error`, zero uncaught `pageerror` exceptions and zero failed critical XHR requests.
3. Measure `documentElement.scrollWidth <= innerWidth` across desktop and mobile viewports.

## User-Flow Validation
- Exercise full user journeys (navigation, form submission, persistence reload, error states), not static screenshots alone.
- Record viewport heights, pass/fail assertions and reproducible failure selectors in the report.
