# Security Concern Tracker

Living document. Updated as we build and discover new concerns.

| # | Concern | Severity | Status | Mitigation |
|---|---------|----------|--------|------------|
| S1 | Agent filesystem access | Critical | Mitigated | Restricted to vault directory, dedicated `ivy` user on Linux |
| S2 | API keys in plaintext | High | Mitigated | .env in .gitignore, password manager backup |
| S3 | Discord bot token | High | Mitigated | Separate bot account, minimal permissions, private server |
| S4 | Third-party skills/plugins | Critical | Mitigated | No third-party code. Everything hand-written |
| S5 | Arbitrary shell execution | Critical | Mitigated | Whitelist-only commands, no sudo |
| S6 | Sensitive info in vault | High | Mitigated | IP policy, .gitignore patterns, separate private repo |
| S7 | Cloud API data exposure | Medium | Accepted | Anthropic's data policy is strong. Sensitive data stays local |
| S8 | Backup repo leaking secrets | High | Mitigated | Pre-push audit hook, .gitignore, no credentials in vault |
| S9 | Network attack surface | Medium | Mitigated | Tailscale only, firewall deny-all inbound, outbound allowlist |
| S10 | Prompt injection via Discord | Medium | Mitigated | Only process Kyle's messages, input sanitization |
| S11 | Ollama model supply chain | Low | Monitoring | Only pull models from official Ollama library |
| S12 | Dependency supply chain | Medium | Monitoring | Pin all Python dependencies, audit before install |

## Adding New Concerns

When you discover a new security concern during development:
1. Add a row to this table with the next S-number
2. Set status to "Open"
3. Describe the mitigation plan
4. Update status when mitigated
