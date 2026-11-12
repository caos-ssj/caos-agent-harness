---
name: mcp-builder
description: Designing or debugging Model Context Protocol (MCP) servers and structured tool schemas for LLM agents.
---

# MCP & Tool Builder

## Schema Design
1. Define tight JSON schemas with explicit required parameters, short unambiguous descriptions and safe defaults.
2. Validate file paths against an explicit workspace root; reject directory traversal and hidden credential files.
3. Prefer read-only structured tools (`read_file`, `grep`, `list_files`) before proposing state-changing operations.

## Reliability
- Bound output sizes cleanly so large directories or diffs do not overflow context windows.
- Return structured, actionable error messages instead of silent failures or stack traces containing credentials.
