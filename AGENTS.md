# AGENTS.md

## Project context
- This repository is a small Python project centered on a bot implementation.
- The main entry point is `bot.py` and the project currently has no additional app structure.
- Favor simple, explicit Python code and keep the architecture lightweight unless the task clearly introduces a larger system.

## Working conventions
- Prefer Python 3.11+ syntax and standard library features before adding third-party packages.
- Keep changes small and readable; add functions or classes only when they improve clarity.
- If the task adds a new feature, prefer a single clear entry point and avoid premature abstraction.
- Do not add framework or dependency scaffolding unless the task or project context explicitly requires it.

## Validation
- Validate Python syntax with:
  - `python -m py_compile bot.py`
- If the code is runnable and the task is behavior-focused, run the relevant script or command directly after changes.
- If a feature is added, prefer targeted verification over broad project setup.

## Notes for AI agents
- Treat this repo as a minimal Python workspace rather than a large service or package.
- When unsure, preserve the current simplicity and do not invent unnecessary project layout.
- Keep prompts, configuration, and environment assumptions explicit and minimal.
