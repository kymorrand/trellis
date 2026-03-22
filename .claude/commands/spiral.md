Let's go do it, dude. Review the current state of your assigned scope and execute one spiral iteration:

1. **PLAN:** Read the sprint plan from `_ivy/reports/sprint-current.md`. Identify the highest-priority incomplete task within your scope. If no sprint plan exists, check git log and README for context on what needs work. Write a brief plan for implementing the task.

2. **PROTOTYPE:** Implement the plan. Keep changes small and focused — one task per spiral. If you're Root, write tests first.

3. **TEST:** Run the test suite: `python -m pytest tests/ -v`. If tests fail, fix them. If no tests exist for your changes and you're Root, write them. Run `ruff check .` for lint.

4. **REVIEW:** Run `git diff` and self-review your changes. Check against CLAUDE.md conventions. Verify you stayed within your scope boundaries (check your agent definition). If anything violates the architecture, fix it before committing.

5. **COMMIT:** If all tests pass and the review looks good, commit with a descriptive message that references the task.

6. **LOG:** Write a status report to `_ivy/reports/status-{your-agent-name}-{date}.md` summarizing: what you did, what tests you wrote/updated, what's blocked, what needs Kyle's input.

7. **NEXT:** Check if there are more tasks in scope. If yes and you've been running less than 30 minutes, start the next spiral iteration. If you've been running 30+ minutes, pause and ensure your status report is written.

If anything needs Kyle's judgment or approval, write it to `_ivy/queue/` as a markdown file with YAML frontmatter (see existing queue items for format).
