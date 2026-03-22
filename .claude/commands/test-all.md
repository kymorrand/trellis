Run the full quality gate for the Trellis codebase:

1. **Tests:** `python -m pytest tests/ -v`
2. **Lint:** `ruff check .`
3. **Import check:** `python -c "from trellis.core.loop import AgentBrain; print('imports OK')"`

Report results clearly:
- Total tests: X passed, X failed, X errors
- Lint: clean or list violations
- Imports: OK or broken (with traceback)

If anything fails, diagnose the root cause and either fix it (if within your scope) or report it in your status.
