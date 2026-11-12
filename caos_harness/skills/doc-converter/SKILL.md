---
name: doc-converter
description: Converting specs, spreadsheets, reports and office documents into structured clean Markdown without losing tables or sections.
---

# Document Conversion & Cleanup

## Extraction Rules
1. Preserve document hierarchy (`#`, `##`, tables, checklists and code blocks) faithfully.
2. Keep dates, measurements and exact identifiers intact; mark unreadable sections or missing pages clearly.
3. Strip secret values, temporary build artifacts and machine-specific paths before packaging team docs.
