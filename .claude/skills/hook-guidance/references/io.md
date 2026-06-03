# Hook I/O

## Stdin: input fields

Common to every event:

```json
{
  "session_id": "abc123",
  "cwd": "/path/to/project",
  "hook_event_name": "PreToolUse"
}
```

Event-specific additions (most-used):

| Event | Adds |
|---|---|
| `PreToolUse` / `PostToolUse` | `tool_name`, `tool_input` |
| `PostToolUseFailure` | `tool_name`, `tool_input`, `tool_response` (with error) |
| `PostToolUse` (success) | `tool_name`, `tool_input`, `tool_response` |
| `UserPromptSubmit` | `prompt` |
| `UserPromptExpansion` | `command_name`, `expanded_prompt` |
| `SessionStart` / `SessionEnd` | `source` |
| `Stop` / `SubagentStop` | `stop_hook_active` (bool — guard against loops) |
| `PreCompact` / `PostCompact` | `trigger`: `manual`/`auto` |
| `ConfigChange` | `source`, `file_path` |
| `FileChanged` | `file_path` |
| `CwdChanged` | `old_cwd`, `new_cwd` |
| `Notification` | `notification_type`, `message` |
| `InstructionsLoaded` | `file_path`, `reason` |

Parse with `jq`:

```bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
```

## Env vars Claude Code provides

- `$CLAUDE_PROJECT_DIR` — repo root. Use for absolute script paths.
- `$CLAUDE_ENV_FILE` — script preamble path. Write `export FOO=bar` here from `SessionStart`/`CwdChanged`/`FileChanged`; Claude sources it before each Bash call.

## Stdout / stderr / exit code

| Exit | Stdout | Stderr | Effect |
|---|---|---|---|
| `0` | Plain text → context (only `UserPromptSubmit`/`UserPromptExpansion`/`SessionStart`); JSON object → structured control | (debug log) | Proceed |
| `0` w/ JSON | Decision JSON | — | Proceed per JSON |
| `2` | (ignored) | Feedback to Claude | Block (events that allow it) |
| other | (proceed) | First line shown as `<hook> hook error`; full → debug log | Proceed |

### Exit code 2 behavior per event

| Event | Exit 2 result |
|---|---|
| `PreToolUse` | Block tool, stderr → Claude |
| `PostToolUse` / `PostToolUseFailure` | Stderr → Claude (tool already ran) |
| `UserPromptSubmit` | Block prompt, stderr → Claude |
| `UserPromptExpansion` | Block expansion |
| `Stop` / `SubagentStop` | Force continuation, stderr → Claude |
| `Notification` / `Setup` / `SessionStart` / `SessionEnd` / `PreCompact` / `PostCompact` / `SubagentStart` / `Cwd*` / `File*` / `Worktree*` | Stderr → user; execution continues |
| `StopFailure` | Output and exit code ignored |

## Structured JSON output (exit 0 + stdout)

### `PreToolUse`

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Use rg, not grep"
  }
}
```

`permissionDecision` values:
- `"allow"` — skip permission prompt (deny rules from settings still apply)
- `"deny"` — cancel, send reason to Claude
- `"ask"` — show prompt as normal
- `"defer"` — `-p`/headless only, exits process preserving call for SDK wrapper

Or rewrite args:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": { "command": "rg pattern" }
  }
}
```

Multiple hooks rewriting same tool's `updatedInput` → last to finish wins (parallel, non-deterministic). Avoid.

### `PermissionRequest`

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow",
      "updatedPermissions": [
        { "type": "setMode", "mode": "acceptEdits", "destination": "session" }
      ]
    }
  }
}
```

`behavior`: `"allow"` / `"deny"`. `mode`: any permission mode (`default`/`acceptEdits`/`bypassPermissions`/`plan`). `bypassPermissions` only if launched with bypass available.

### `PostToolUse` / `Stop` / `SubagentStop`

```json
{ "decision": "block", "reason": "tests failed" }
```

For `Stop`: feeds reason as Claude's next instruction → continues working.

### `UserPromptSubmit`

```json
{ "additionalContext": "Reminder: use Bun. Don't run npm." }
```

Appended as system reminder. Plain text — cannot trigger tool calls.

### `PermissionDenied`

```json
{ "retry": true }
```

Tells the model it may retry the denied call.

### `ConfigChange`

```json
{ "decision": "block" }
```

Reverts the change.

## Decision precedence (multiple matching hooks)

Most restrictive wins. `deny` > `ask` > `allow`. `additionalContext` from each hook concatenates.

Hooks tighten only — `allow` from a hook does NOT override settings deny rules.
