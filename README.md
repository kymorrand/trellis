# Trellis 🌱

**An experimental personal agent runtime — prototyping context management patterns for human-AI coordination.**

Trellis is a lightweight, modular framework for running a persistent AI assistant on dedicated hardware. It implements the [4C cycle](https://mirrorfactory.ai) (Collect → Curate → Coordinate → Compound) as a working agent loop, using file-based Markdown memory, hybrid local/cloud inference, and game-design-inspired architecture.

> **⚠️ This is an experiment, not a product.** Trellis is a personal R&D project by [Kyle Morrand](https://morrandmore.com), CEO of [Mirror Factory](https://mirrorfactory.ai). It serves as a paper prototype for the architectural principles behind Layers, Mirror Factory's context management platform. Learnings feed back into the product. Code stays here. See [EXPERIMENT.md](EXPERIMENT.md) for details.

## What Is This?

Trellis is the runtime. **Ivy** is the first agent running on it — a professional AI assistant that handles research, task management, knowledge curation, and autonomous background work ("side quests").

Think of it like a game engine: Trellis provides the main loop, state persistence, I/O handling, and a tool system. Ivy is the character — defined by her personality (`SOUL.md`), her knowledge base (an Obsidian vault), and her behavioral roles.

## Architecture

```
┌─────────────────────────────────────────────┐
│                TRELLIS RUNTIME               │
│                                              │
│  ┌─────────┐   ┌─────────┐   ┌──────────┐  │
│  │  LISTEN  │──▶│  THINK  │──▶│   ACT    │  │
│  │ (events) │   │ (model) │   │ (tools)  │  │
│  └─────────┘   └─────────┘   └──────────┘  │
│       ▲                            │         │
│       │         ┌─────────┐        │         │
│       └─────────│ PERSIST │◀───────┘         │
│                 │ (state) │                  │
│                 └─────────┘                  │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │          HEARTBEAT SCHEDULER          │   │
│  │  (proactive ticks on cron schedule)   │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

**Modules:**

| Module | Game Analogy | Function |
|--------|-------------|----------|
| `core/` | Game loop | Event loop and heartbeat scheduler |
| `mind/` | AI brain / decision engine | Model routing, context assembly, personality |
| `senses/` | Input manager | Discord, file watcher, CLI |
| `hands/` | Action system | Vault writes, Linear, calendar, GitHub |
| `memory/` | Save system | Journal, knowledge management, compaction |
| `security/` | Permission system | Access control, sanitization, audit trail |

## Design Principles

1. **Modular.** Every component is swappable. Models, APIs, channels, storage — all behind clean interfaces.
2. **Anthropic-first.** Claude is the primary cloud model. MCP is the interoperability standard.
3. **File-based.** Knowledge is Markdown on disk. State is JSON on disk. Human-readable, version-controllable, Obsidian-compatible.
4. **Conservative security.** Least privilege everywhere. No third-party plugins. Sandboxed execution.
5. **Experiment, not product.** Move fast, document everything, break things that teach you something.

## Inspired By

Trellis draws architectural inspiration from [OpenClaw](https://github.com/openclaw/openclaw) (dual-loop reactive + proactive agent design, file-based Markdown memory), [claw0](https://github.com/shareAI-lab/claw0) (progressive tutorial approach to agent internals), and over a decade of real-time game engine design in Unity. It's built from scratch to learn, not forked to ship.

## Getting Started

Coming soon — Trellis is under active development. Follow the build log in [`docs/build-log/`](docs/build-log/) or read about the journey at [morrandmore.com](https://morrandmore.com).

## License

MIT — see [LICENSE](LICENSE).
