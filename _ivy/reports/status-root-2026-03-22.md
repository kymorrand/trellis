# Root Status Report — 2026-03-22

## Task
Write missing test coverage for `core/loop.py`, `hands/shell.py`, and `memory/compactor.py`.

## Deliverables

### `tests/test_shell.py` — 27 tests
- **TestValidateCommand** (18 tests): Whitelist enforcement, blocked patterns (sudo, rm, pip install, eval, subshell, backtick, pipe-to-bash, --force, --hard), empty/whitespace commands, pipe chain validation, invalid syntax, full-path commands.
- **TestExecuteCommand** (9 tests): Simple execution, blocked command returns error string, cwd respected, stderr included in output, non-zero exit code shown, output truncation at MAX_OUTPUT, empty output placeholder, pipe execution.

### `tests/test_compactor.py` — 20 tests
- **TestEstimateTokens** (4 tests): Empty string, single word, multi-word, returns int.
- **TestEstimateHistoryTokens** (3 tests): Empty history, sums all messages, handles missing content key.
- **TestSummarize** (4 tests): Short text passthrough, long text truncation, multiline first-line extraction, short-first-line expansion.
- **TestCompactHistory** (9 tests): Empty history, short history unchanged, returns list copy, long history compacted, recent messages preserved at full detail, old messages get omitted marker, odd message count handling, within-budget passthrough, custom parameter support.

### `tests/test_loop.py` — 30 tests
- **TestEvent** (2 tests): Default construction, full construction with all fields.
- **TestToolDefinitions** (2 tests): Required fields present, expected tool names present.
- **TestToolExecutor** (16 tests): vault_search, vault_read, vault_save, shell_execute (allowed + blocked), journal_read (exists + missing date), unknown tool, Permission.DENY, Permission.ASK, agent state updates, error handling, permission key mapping, large file truncation.
- **TestAgentBrain** (10 tests): Construction, role fallback, system prompt building (default + custom role), local routing, cloud ReAct loop (no tools), ReAct loop with tool call, MAX_TOOL_ROUNDS enforcement, local-to-cloud fallback, force_local no fallback.

## Verification
- `python -m pytest tests/ -v` — **173 passed** in 60.57s
- `ruff check .` — **clean**
- No changes to existing source modules; test-only additions.

## Notes
- All AgentBrain tests mock the Anthropic client and ModelRouter — no API calls.
- ToolExecutor tests use real vault fixtures (tmp_path) for integration-level coverage.
- Shell tests use real subprocess execution for `execute_command` (safe commands only).
