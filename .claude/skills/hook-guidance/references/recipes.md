# Recipes

Drop-in configs. Add to `~/.claude/settings.json` (user-wide) or `.claude/settings.json` (project) unless noted.

## Desktop notify on idle

macOS:

```json
{
  "hooks": {
    "Notification": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "osascript -e 'display notification \"Claude Code needs your attention\" with title \"Claude Code\"'" }] }
    ]
  }
}
```

If `osascript` doesn't fire: run once in Terminal, then **System Settings > Notifications > Script Editor** → Allow.

Linux: `notify-send 'Claude Code' 'Needs attention'`

Windows: `powershell.exe -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); [System.Windows.Forms.MessageBox]::Show('Claude Code needs your attention','Claude Code')"`

## Auto-format on edit

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{ "type": "command", "command": "jq -r '.tool_input.file_path' | xargs npx prettier --write" }]
      }
    ]
  }
}
```

## Block edits to protected files

`.claude/hooks/protect-files.sh`:

```bash
#!/bin/bash
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
PATTERNS=(".env" "package-lock.json" ".git/")
for p in "${PATTERNS[@]}"; do
  if [[ "$FILE_PATH" == *"$p"* ]]; then
    echo "Blocked: $FILE_PATH matches '$p'" >&2
    exit 2
  fi
done
exit 0
```

`chmod +x` then:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/protect-files.sh" }]
      }
    ]
  }
}
```

## Re-inject context after compaction

Stdout from `SessionStart` hook → context.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [{ "type": "command", "command": "echo 'Use Bun, not npm. Run bun test before commit.'" }]
      }
    ]
  }
}
```

For session-start every time, prefer CLAUDE.md. For env vars, use `$CLAUDE_ENV_FILE`.

## Audit config changes

```json
{
  "hooks": {
    "ConfigChange": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "jq -c '{timestamp: now | todate, source: .source, file: .file_path}' >> ~/claude-config-audit.log" }]
      }
    ]
  }
}
```

Block instead: exit 2 or return `{"decision": "block"}`.

## Reload direnv on cwd / file change

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "direnv export bash > \"$CLAUDE_ENV_FILE\"" }] }
    ],
    "CwdChanged": [
      { "hooks": [{ "type": "command", "command": "direnv export bash > \"$CLAUDE_ENV_FILE\"" }] }
    ],
    "FileChanged": [
      {
        "matcher": ".envrc|.env",
        "hooks": [{ "type": "command", "command": "direnv export bash > \"$CLAUDE_ENV_FILE\"" }]
      }
    ]
  }
}
```

`FileChanged` matcher takes literal filenames split by `|`, NOT regex. `direnv allow` once per `.envrc`. Swap `direnv export bash` for `devbox shellenv` if using devbox/nix.

## Auto-approve `ExitPlanMode`

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "matcher": "ExitPlanMode",
        "hooks": [{ "type": "command", "command": "echo '{\"hookSpecificOutput\": {\"hookEventName\": \"PermissionRequest\", \"decision\": {\"behavior\": \"allow\"}}}'" }]
      }
    ]
  }
}
```

Switch to `acceptEdits` after approval:

```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow","updatedPermissions":[{"type":"setMode","mode":"acceptEdits","destination":"session"}]}}}
```

Keep matcher narrow. `.*` would auto-approve every prompt.

## Validate Bash before exec

```bash
#!/bin/bash
INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command')
if echo "$CMD" | grep -iqE '\b(drop\s+table|rm\s+-rf\s+/|:\(\)\{)\b'; then
  echo "Blocked: dangerous pattern" >&2
  exit 2
fi
exit 0
```

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/validate-bash.sh" }]
      }
    ]
  }
}
```

Use `if` field (v2.1.85+) for narrower triggering — only spawn the script when subcommand matches:

```json
{ "type": "command", "if": "Bash(rm *)", "command": "..." }
```

## Log every Bash command

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "jq -r '.tool_input.command' >> ~/.claude/command-log.txt" }]
      }
    ]
  }
}
```

## Stop hook with loop guard

```bash
#!/bin/bash
INPUT=$(cat)
if [ "$(echo "$INPUT" | jq -r '.stop_hook_active')" = "true" ]; then
  exit 0
fi
# work here, optionally exit 2 to force continuation
```

Without the guard, your `Stop` hook will infinite-loop the session.

## Cleanup on `/clear`

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "clear",
        "hooks": [{ "type": "command", "command": "rm -f /tmp/claude-scratch-*.txt" }]
      }
    ]
  }
}
```

## HTTP audit endpoint

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "hooks": [{
          "type": "http",
          "url": "http://localhost:8080/hooks/tool-use",
          "headers": { "Authorization": "Bearer $TOKEN" },
          "allowedEnvVars": ["TOKEN"]
        }]
      }
    ]
  }
}
```

## Subagent lifecycle in main session

```json
{
  "hooks": {
    "SubagentStart": [
      { "matcher": "db-agent", "hooks": [{ "type": "command", "command": "./scripts/setup-db.sh" }] }
    ],
    "SubagentStop": [
      { "hooks": [{ "type": "command", "command": "./scripts/cleanup-db.sh" }] }
    ]
  }
}
```

For hooks that fire *while* a subagent is active, put them in the subagent's frontmatter (Stop becomes SubagentStop at runtime).
