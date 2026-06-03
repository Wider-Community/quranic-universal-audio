---
name: hook-guidance
description: Reference for authoring, debugging, and reasoning about Claude Code hooks. Use whenever the user wants to add/edit/remove a hook, pick a hook event, write a matcher, decide between command/http/mcp_tool/prompt/agent hook types.
---

# Hook Guidance

Hooks = shell commands (or HTTP/MCP/LLM evals) that fire at lifecycle points. Deterministic vs. relying on the model. Use to enforce rules, format on save, inject context, audit, gate dangerous tools.

## When hooks vs. alternatives

| Want | Use |
|---|---|
| Run shell on every X event, regardless of model judgment | **Hook** |
| Reusable prompt/instructions Claude reads | **Skill** |
| Isolated context worker | **Subagent** |
| Permission allow/deny rules without scripting | **Permissions** (`/permissions`) |
| Bundled extension (hooks + skills + agents) | **Plugin** |

Reach for `type: "prompt"` / `"agent"` hooks only when judgment beats deterministic rules.

## Authoring workflow

1. **Pick event.** What lifecycle point fires it? See `references/events.md`.
2. **Pick scope.** User vs project vs local vs plugin. See table below.
3. **Pick type.** `command` (default) vs `http` vs `mcp_tool` vs `prompt` vs `agent`. See `references/types.md`.
4. **Write matcher.** Narrow to specific tools/sources. Add `if` for tool-arg filtering (v2.1.85+). See `references/events.md`.
5. **Wire input/output.** Stdin = JSON event data. Stdout/stderr/exit code drive behavior. JSON output for fine control. See `references/io.md`.
6. **Test.** Pipe sample JSON to script, check exit code. Use `claude --debug-file /tmp/claude.log` then `tail -f`.
7. **Verify.** Run `/hooks` in Claude Code — read-only browser of all configured hooks.

## Config locations

| File | Scope | Shareable |
|---|---|---|
| `~/.claude/settings.json` | All your projects | No |
| `<repo>/.claude/settings.json` | Project, committed | Yes |
| `<repo>/.claude/settings.local.json` | Project, gitignored | No |
| Managed policy settings | Org-wide | Admin only |
| Plugin `hooks/hooks.json` | While plugin enabled | Yes |
| Skill / subagent frontmatter | While component active | Yes |

Edit JSON directly — `/hooks` is read-only. File watcher reloads automatically; restart session if it doesn't pick up.

Nuke switch: `"disableAllHooks": true` in any settings file.

## Minimum viable hook

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "jq -r '.tool_input.file_path' | xargs npx prettier --write" }
        ]
      }
    ]
  }
}
```

`hooks` is one object. Each event name (`PreToolUse`, `Stop`, etc.) is a sibling key inside it. Don't replace the whole `hooks` object when adding a new event — add a sibling key.

## Input contract

Stdin = JSON. Always includes:

```json
{ "session_id": "...", "cwd": "...", "hook_event_name": "PreToolUse" }
```

Plus event-specific fields. `PreToolUse` adds `tool_name`, `tool_input`. `UserPromptSubmit` adds `prompt`. `SessionStart` adds `source`. Full schemas: `references/events.md`.

## Output contract (command hooks)

| Exit | Effect |
|---|---|
| `0` | Proceed. Stdout → context for `UserPromptSubmit`/`UserPromptExpansion`/`SessionStart`; ignored elsewhere |
| `2` | Block. Stderr → fed back to Claude as feedback. Some events ignore the block (see `references/io.md`) |
| other | Proceed with `<hook> hook error` notice. Stderr → debug log |

For finer control: exit 0 + structured JSON to stdout. Don't mix exit 2 with JSON — exit 2 wins.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Use rg, not grep"
  }
}
```

Per-event decision schema: `references/io.md`.

## Common recipes

Drop-in configs in `references/recipes.md`:
- Desktop notify on idle
- Auto-format after edits
- Block edits to protected files
- Re-inject context after compaction
- Audit config changes
- Reload direnv on cwd/file change
- Auto-approve `ExitPlanMode`
- Validate Bash commands before exec

## Matchers

Match field varies by event. Quick reference:

| Event | Matcher matches |
|---|---|
| `PreToolUse` / `PostToolUse` / `PostToolUseFailure` / `PermissionRequest` / `PermissionDenied` | Tool name (regex, e.g. `Edit\|Write`, `mcp__github__.*`) |
| `SessionStart` | `startup` / `resume` / `clear` / `compact` |
| `SessionEnd` | `clear` / `resume` / `logout` / `prompt_input_exit` / `bypass_permissions_disabled` / `other` |
| `Notification` | `permission_prompt` / `idle_prompt` / `auth_success` / `elicitation_*` |
| `SubagentStart` / `SubagentStop` | Agent type name |
| `PreCompact` / `PostCompact` | `manual` / `auto` |
| `ConfigChange` | `user_settings` / `project_settings` / `local_settings` / `policy_settings` / `skills` |
| `FileChanged` | Pipe-separated literal filenames (NOT regex) |
| `UserPromptSubmit` / `Stop` / `PostToolBatch` / `CwdChanged` / `WorktreeCreate` / etc. | No matcher; always fires |

Full list: `references/events.md`.

## Hook types beyond `command`

Use when shell-out doesn't fit:

- `http` — POST event JSON to URL, parse response body as JSON output. Header env-var interpolation requires `allowedEnvVars`.
- `mcp_tool` — call tool on connected MCP server.
- `prompt` — single LLM call (Haiku default) returns `{"ok": bool, "reason": str}`. For judgment calls.
- `agent` — multi-turn subagent with tools (60s default timeout, 50 turns). Experimental. For verification needing file reads/grep/test runs.

Schemas: `references/types.md`.

## Decision precedence

Multiple matching hooks → most restrictive wins. `deny` > `ask` > `allow`. `additionalContext` from all hooks concatenates.

Hooks tighten, can't loosen: a hook returning `allow` does NOT bypass deny rules from `permissions`. Deny in any settings scope always wins.

Inverse: a `PreToolUse` hook returning `deny` blocks even in `bypassPermissions` / `--dangerously-skip-permissions`. Use to enforce policy users can't bypass.

## Limitations

- Command hooks talk via stdout/stderr/exit only. Cannot trigger `/` commands or tool calls.
- `additionalContext` is plain-text system reminder, not a tool call.
- `PostToolUse` cannot undo (tool already ran).
- `PermissionRequest` does not fire in `-p` / headless. Use `PreToolUse` for headless gating.
- `Stop` fires every time Claude finishes responding, not only at task completion. Doesn't fire on user interrupts; API errors fire `StopFailure` instead.
- Multiple `PreToolUse` hooks rewriting `updatedInput` → last-to-finish wins (parallel, non-deterministic). Don't have two hooks rewriting the same tool's args.
- Default timeout 10 min. Override per hook with `timeout` (seconds).


## Reference files

- `references/events.md` — every event, when it fires, matcher field, decision-control schema
- `references/io.md` — full input fields, JSON output schemas per event, exit-code-2 behavior table
- `references/types.md` — command/http/mcp_tool/prompt/agent fields and examples
- `references/recipes.md` — copy-paste configs for common tasks