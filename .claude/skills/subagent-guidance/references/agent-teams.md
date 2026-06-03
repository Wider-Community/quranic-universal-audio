# Agent Teams

Experimental. Requires Claude Code v2.1.32+. Enable with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (env or `settings.json` `env` block).

A team is multiple Claude Code instances working together. One session is the **lead**; the rest are **teammates**, each with its own context window. Unlike subagents, teammates message each other directly via a shared mailbox and claim work from a shared task list.

## Subagents vs teams — pick by communication need

| | Subagents | Agent teams |
|---|---|---|
| Context | Own window, results return to caller | Own window, fully independent |
| Communication | Report to main agent only | Teammates message each other directly |
| Coordination | Main agent manages all work | Shared task list with self-claim |
| Best for | Focused tasks where only result matters | Work needing discussion + collaboration |
| Token cost | Lower (results summarized) | Higher (each teammate is a full Claude instance) |

Pick teams when teammates need to challenge each other's findings, share intermediate state, or self-coordinate. Pick subagents for parallel-but-isolated work that just needs to report back.

Strongest team use cases:
- Research/review with distinct lenses (security, perf, tests on the same PR)
- New modules or features split by ownership
- Debugging with competing hypotheses (adversarial debate)
- Cross-layer coordination (frontend / backend / tests)

Avoid teams for sequential work, same-file edits, or routine tasks — coordination overhead exceeds the benefit.

## Starting a team

The user describes the task and team shape in natural language; Claude creates the team, spawns teammates, and coordinates:

```
I'm designing a CLI for tracking TODO comments. Create an agent team to
explore from different angles: one teammate on UX, one on technical
architecture, one playing devil's advocate.
```

Claude won't create a team without user approval — either the user requests it explicitly, or Claude proposes one and the user confirms.

To pin team size and model, the user can specify:

```
Create a team with 4 teammates to refactor these modules in parallel.
Use Sonnet for each teammate.
```

## Use case patterns

### Parallel code review with distinct lenses

A single reviewer gravitates toward one issue type. Splitting the criteria forces simultaneous coverage. Each teammate gets a distinct lens so they don't overlap; the lead synthesizes after.

```
Create an agent team to review PR #142. Spawn three reviewers:
- One focused on security implications
- One checking performance impact
- One validating test coverage
Have them each review and report findings.
```

### Competing-hypothesis debate (root cause)

When the cause is unclear, a single agent finds one plausible explanation and stops. Force adversarial debate so the surviving theory is more likely correct.

```
Users report the app exits after one message instead of staying connected.
Spawn 5 agent teammates to investigate different hypotheses. Have them talk
to each other to try to disprove each other's theories, like a scientific
debate. Update the findings doc with whatever consensus emerges.
```

The debate structure beats sequential investigation — sequential suffers from anchoring once the first theory is explored.

## Display modes

| Mode | Behavior |
|---|---|
| In-process | All teammates run in the main terminal. `Shift+Down` cycles through teammates. Works in any terminal. |
| Split panes | Each teammate gets its own pane. Requires tmux or iTerm2 with the `it2` CLI + Python API enabled. |

`teammateMode` setting in `~/.claude/settings.json`: `"auto"` (default — split if already in tmux, else in-process), `"in-process"`, `"tmux"`. Per-session override: `claude --teammate-mode in-process`.

In-process navigation:
- `Shift+Down` — cycle teammates (wraps back to lead after last)
- `Enter` — view a teammate's session
- `Esc` — interrupt their current turn
- `Ctrl+T` — toggle task list

Split-pane: click into a pane to interact directly.

## Architecture

| Component | Role |
|---|---|
| Team lead | Main session that creates the team, spawns teammates, coordinates |
| Teammates | Separate Claude Code instances per assigned task |
| Task list | Shared work items with three states: pending, in progress, completed. Tasks can declare dependencies; dependent tasks unblock automatically. |
| Mailbox | Direct messaging between agents |

Storage:
- Team config: `~/.claude/teams/{team-name}/config.json` — runtime state (session IDs, tmux pane IDs). Don't edit by hand; overwritten on next state update.
- Task list: `~/.claude/tasks/{team-name}/`

No project-level config (`.claude/teams/teams.json` is treated as an ordinary file, not config).

The team config has a `members` array (name, agent ID, agent type) — teammates can read it to discover peers.

## Spawning with subagent definitions

Reference any subagent type (project, user, plugin, CLI-defined) by name when spawning a teammate:

```
Spawn a teammate using the security-reviewer agent type to audit auth.
```

Effect:
- Teammate honors the definition's `tools` allowlist and `model`.
- Definition's body is **appended** to the teammate's system prompt (not replacing it).
- `SendMessage` and task management tools are always available, even if `tools` restricts others.

⚠️ `skills` and `mcpServers` from the subagent definition are NOT applied when running as a teammate. Teammates load skills + MCP servers from project/user settings like a regular session.

## Permissions

Teammates start with the lead's permission settings. `--dangerously-skip-permissions` propagates. After spawning, you can change individual teammate modes — but you can't set per-teammate modes at spawn time. Permission requests bubble to the lead.

## Context

Each teammate loads CLAUDE.md, MCP servers, and skills like a regular session. The lead's conversation history does NOT carry over — include task-specific detail in the spawn prompt:

```
Spawn a security reviewer with prompt: "Review src/auth/ for vulnerabilities.
Focus on token handling, sessions, and input validation. App uses JWT in
httpOnly cookies. Report issues with severity ratings."
```

## Communication mechanics

- **Auto delivery** — messages between teammates land automatically; lead doesn't poll.
- **Idle notifications** — when a teammate stops, the lead is notified.
- **Shared task list** — all agents see status, claim available work.
- **Targeted messaging** — send to one teammate by name; broadcast = one message per recipient.

The lead names each teammate at spawn. Tell the lead what to call them so you can reference them later.

## Plan approval gating

For risky tasks, require teammates to plan before implementing. They work in read-only plan mode until the lead approves:

```
Spawn an architect teammate to refactor auth. Require plan approval before
they make any changes.
```

The teammate sends a plan to the lead. Lead approves or rejects with feedback. Rejected plans stay in plan mode and resubmit. Lead decides autonomously — to influence: "only approve plans that include test coverage" or "reject plans that modify the database schema".

## Task assignment

- **Lead assigns** — tell the lead which task goes to which teammate.
- **Self-claim** — after finishing, a teammate picks the next unassigned, unblocked task.

File locking prevents race conditions on simultaneous claims.

## Hooks for quality gates

| Hook | Behavior on exit code 2 |
|---|---|
| `TeammateIdle` | Send feedback, keep teammate working |
| `TaskCreated` | Block creation, send feedback |
| `TaskCompleted` | Block completion, send feedback |

## Shutdown and cleanup

Graceful per-teammate shutdown:
```
Ask the researcher teammate to shut down
```
Lead sends shutdown request; teammate can approve or reject with explanation.

Team cleanup:
```
Clean up the team
```

Cleanup removes shared resources. **Always run cleanup from the lead** — teammates running cleanup may leave resources in inconsistent state. Cleanup fails if any teammate is still running; shut them down first.

## Token cost

Scales linearly per teammate. Start with 3-5 teammates; aim for 5-6 tasks per teammate. Three focused teammates often outperform five scattered ones.

## Best practices

- Wait for teammates to finish before the lead implements: "Wait for your teammates to complete their tasks before proceeding."
- Start with research/review (clear boundaries, no parallel writes) before parallel implementation.
- Break work so each teammate owns distinct files — concurrent same-file edits cause overwrites.
- Pre-approve common operations in permission settings to reduce prompt friction.
- Monitor and steer; don't leave a team unattended.

## Known limitations

- **No session resume for in-process teammates** — `/resume` and `/rewind` don't restore them. After resume, lead may message ghosts. Tell it to spawn new teammates.
- **Task status can lag** — teammates sometimes fail to mark complete, blocking dependents. Check actual progress; update manually or nudge.
- **Shutdown is slow** — teammates finish current request/tool call first.
- **One team per session** — clean up before starting a new team.
- **No nested teams** — teammates cannot spawn teams or teammates.
- **Lead is fixed** — the creating session leads for the team's lifetime. No promotion or transfer.
- **Permissions set at spawn** — see Permissions section.
- **Split panes need tmux or iTerm2** — not supported in VS Code integrated terminal, Windows Terminal, or Ghostty.

## Troubleshooting

- **Teammates invisible (in-process)** — `Shift+Down` to cycle.
- **No team created** — task may not be complex enough; Claude decides.
- **Split panes broken** — `which tmux`; for iTerm2 verify `it2` CLI + Python API enabled in iTerm2 → Settings → General → Magic.
- **Teammate stuck on error** — check output, give direct instructions, or spawn a replacement.
- **Lead shuts down too early** — tell it to keep going / wait.
- **Orphaned tmux session** — `tmux ls`, `tmux kill-session -t <name>`.
