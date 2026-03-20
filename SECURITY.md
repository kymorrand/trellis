# Security Policy

Trellis runs an AI agent with access to local files, APIs, and communication channels. Security is not optional.

## Principles

1. **Least privilege.** The agent only accesses what it needs for the current task.
2. **No third-party plugins.** Every tool and skill is hand-written. No marketplace installs, no unvetted code.
3. **Sandboxed execution.** Shell commands are whitelisted. No `sudo`. No arbitrary code execution.
4. **Audit everything.** Every action the agent takes is logged with timestamp, type, target, and result.
5. **Anthropic-aligned.** Follow Anthropic's MCP best practices for tool use and interoperability.

## Credential Management

- All API keys and tokens live in `.env` — never in code, never committed
- Each service gets a dedicated, scoped API key (labeled: `IVY_ANTHROPIC_KEY`, `IVY_DISCORD_TOKEN`, etc.)
- Backup credentials in a password manager (1Password, Bitwarden)
- Rotate keys quarterly

## Known Concerns

See the Security Concern Tracker in [`docs/security-log.md`](docs/security-log.md) for the living list of identified risks and mitigations.

## Reporting

If you find a security issue in Trellis, please open an issue or email kyle@morrandmore.com. This is an experiment, not production software, but responsible disclosure is still appreciated.
