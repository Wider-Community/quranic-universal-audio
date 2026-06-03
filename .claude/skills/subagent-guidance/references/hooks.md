# Hooks for Subagents

Two surfaces for subagent-related hooks:

1. **Frontmatter hooks** — fire while this subagent is active.
2. **`settings.json` hooks** — fire in main session at subagent lifecycle events.

## Frontmatter hooks

Run when the agent is spawned as a subagent (Agent tool / @-mention) AND when it runs as main session via `--agent` or the `agent` setting. In the main-session case they run alongside `settings.json` hooks.

All hook events supported. Common ones:

| Event | Matcher | Fires |
|---|---|---|
| `PreToolUse` | Tool name | Before tool use |
| `PostToolUse` | Tool name | After tool use |
| `Stop` | (none) | When subagent finishes — converted to `SubagentStop` at runtime |

```yaml
---
name: code-reviewer
description: Review code with auto-linting
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate-command.sh $TOOL_INPUT"
  PostToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: command
          command: "./scripts/run-linter.sh"
---
```

## settings.json: subagent lifecycle

| Event | Matcher | Fires |
|---|---|---|
| `SubagentStart` | Agent type name | Subagent begins |
| `SubagentStop` | Agent type name | Subagent completes |

```json
{
  "hooks": {
    "SubagentStart": [
      {
        "matcher": "db-agent",
        "hooks": [{ "type": "command", "command": "./scripts/setup-db.sh" }]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [{ "type": "command", "command": "./scripts/cleanup-db.sh" }]
      }
    ]
  }
}
```

## Validation pattern (PreToolUse blocking)

Hook input arrives via stdin as JSON. Exit 2 blocks the operation; stderr feeds back to Claude.

```bash
#!/bin/bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if echo "$COMMAND" | grep -iE '\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE)\b' > /dev/null; then
  echo "Blocked: read-only access only" >&2
  exit 2
fi
exit 0
```

Make executable: `chmod +x scripts/validate-readonly-query.sh`.

See `/en/hooks` for full input schema and exit code semantics.
