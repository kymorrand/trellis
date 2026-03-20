"""trellis.hands.shell — Sandboxed Shell Execution

Whitelisted shell commands only. No sudo. No arbitrary execution.
Security: This is the most dangerous tool. Treat with extreme caution.

Whitelist: git, ls, cat, grep, find, wc, date, echo, curl (specific endpoints only)
"""
# TODO: Phase 1 implementation
# - Command whitelist validation before execution
# - No sudo, no rm -rf, no package installs
# - Timeout on all commands (30s max)
# - Full audit logging of every command and output
