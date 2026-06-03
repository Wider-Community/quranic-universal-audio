# Hook Events

Full lifecycle table. Each event fires all matching hooks in parallel; identical commands deduped.

## Lifecycle table

| Event | Fires | Matcher field | Blockable via exit 2 |
|---|---|---|---|
| `SessionStart` | Session begin/resume | `startup`/`resume`/`clear`/`compact` | No (stderr → user) |
| `Setup` | `--init-only`, or `--init`/`--maintenance` in `-p` | `init`/`maintenance` | No |
| `UserPromptSubmit` | Prompt submitted, before Claude sees it | none | Yes |
| `UserPromptExpansion` | Typed command expands to prompt | command name | Yes |
| `PreToolUse` | Before tool call | tool name (regex) | Yes |
| `PermissionRequest` | Permission dialog about to show | tool name | Yes (writes JSON to allow/deny) |
| `PermissionDenied` | Auto mode classifier denied a call | tool name | n/a (return `{retry: true}` to allow retry) |
| `PostToolUse` | After tool succeeds | tool name | Yes (feeds back to model) |
| `PostToolUseFailure` | After tool fails | tool name | Yes |
| `PostToolBatch` | After parallel tool batch resolves | none | Yes |
| `Notification` | Claude Code sends notification | type (see below) | No |
| `SubagentStart` | Subagent spawned | agent type | n/a |
| `SubagentStop` | Subagent finished | agent type | Yes |
| `TaskCreated` | `TaskCreate` runs | none | Yes |
| `TaskCompleted` | Task marked completed | none | Yes |
| `Stop` | Claude finishes responding | none | Yes (forces continuation) |
| `StopFailure` | Turn ended via API error | error type | Output ignored |
| `TeammateIdle` | Agent-team teammate going idle | none | Yes |
| `InstructionsLoaded` | CLAUDE.md / `.claude/rules/*.md` loaded | load reason | Yes |
| `ConfigChange` | Config file changed mid-session | source (see below) | Yes (`{"decision":"block"}`) |
| `CwdChanged` | Working directory changed | none | n/a |
| `FileChanged` | Watched file changed on disk | literal filenames piped | n/a |
| `WorktreeCreate` | Worktree creating (replaces default git) | none | n/a |
| `WorktreeRemove` | Worktree removing | none | n/a |
| `PreCompact` | Before context compaction | `manual`/`auto` | Yes |
| `PostCompact` | After compaction | `manual`/`auto` | n/a |
| `Elicitation` | MCP server requests user input | MCP server name | Yes |
| `ElicitationResult` | After user responds to MCP elicitation | MCP server name | Yes |
| `SessionEnd` | Session terminates | end reason (see below) | No |

## Matcher value enums

- `Notification`: `permission_prompt` / `idle_prompt` / `auth_success` / `elicitation_dialog` / `elicitation_complete` / `elicitation_response`
- `SessionEnd`: `clear` / `resume` / `logout` / `prompt_input_exit` / `bypass_permissions_disabled` / `other`
- `ConfigChange`: `user_settings` / `project_settings` / `local_settings` / `policy_settings` / `skills`
- `StopFailure`: `rate_limit` / `authentication_failed` / `oauth_org_not_allowed` / `billing_error` / `invalid_request` / `server_error` / `max_output_tokens` / `unknown`
- `InstructionsLoaded`: `session_start` / `nested_traversal` / `path_glob_match` / `include` / `compact`

## Tool-name matcher syntax

Regex against tool name. Examples:

| Pattern | Matches |
|---|---|
| `Bash` | only `Bash` |
| `Edit\|Write` | `Edit` or `Write` |
| `mcp__github__.*` | all GitHub MCP tools |
| `mcp__.*__write.*` | any MCP tool starting with `write` |
| `.*` | every tool (avoid for `PermissionRequest` — auto-approves everything) |

MCP tool naming: `mcp__<server>__<tool>`.

## `if` field (v2.1.85+)

Filters by tool args, not just tool name. Permission-rule syntax. Spawns hook process only on match.

```json
{
  "matcher": "Bash",
  "hooks": [
    { "type": "command", "if": "Bash(git *)", "command": "..." }
  ]
}
```

- Compound commands (`npm test && git push`) — fires if any subcommand matches.
- Multiple tool names → separate handlers each with its own `if`. `if` doesn't accept pipe alternation; matcher does.
- Only valid on tool events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`. Adding it elsewhere prevents the hook from running.

## Decision-control output schema by event

| Event | Output mechanism |
|---|---|
| `PreToolUse` | `hookSpecificOutput.permissionDecision`: `allow`/`deny`/`ask`/`defer` + `permissionDecisionReason`. Or `updatedInput` to rewrite tool args |
| `PermissionRequest` | `hookSpecificOutput.decision.behavior`: `allow`/`deny`. Optional `updatedPermissions: [{type:"setMode", mode, destination:"session"}]` |
| `PostToolUse` / `Stop` / `SubagentStop` | Top-level `decision: "block"` + `reason` |
| `UserPromptSubmit` | `additionalContext` (string) appended to context |
| `PermissionDenied` | `{retry: true}` to let the model retry |
| `ConfigChange` | `{decision: "block"}` to revert |
| `SessionStart` / `UserPromptSubmit` / `UserPromptExpansion` | Stdout (exit 0) appended to context |

`bypassPermissions` only applies if session was launched with bypass available. Never persisted as `defaultMode`.

## Permission-mode interaction

`PreToolUse` `deny` blocks even in `--dangerously-skip-permissions`. `allow` does NOT bypass deny rules from settings. Deny rules in any scope always win.
