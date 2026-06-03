# Hook Types

Each hook entry has a `type`. Most use `command`. Four others exist for different use cases.

## `command` (default)

Spawn a shell process. Stdin = JSON event. Exit/stdout/stderr = control.

```json
{
  "type": "command",
  "command": "/abs/path/to/script.sh",
  "timeout": 30
}
```

- `command`: shell string. Runs in a non-interactive shell that sources `~/.zshrc`/`~/.bashrc`. Guard echo statements with `if [[ $- == *i* ]]; then ... fi` or stdout JSON breaks.
- `timeout`: seconds. Default 600 (10 min).
- Use `$CLAUDE_PROJECT_DIR` for portable script paths.

Make scripts executable: `chmod +x .claude/hooks/foo.sh`.

## `http`

POST event JSON to URL; response body = output JSON.

```json
{
  "type": "http",
  "url": "http://localhost:8080/hooks/audit",
  "headers": { "Authorization": "Bearer $TOKEN" },
  "allowedEnvVars": ["TOKEN"],
  "timeout": 10
}
```

- Header values support `$VAR` / `${VAR}` interpolation, but only for vars in `allowedEnvVars`.
- HTTP status codes alone cannot block. Return 2xx with `hookSpecificOutput.permissionDecision: "deny"` to block.
- Same JSON output schema as command hooks.

## `mcp_tool`

Call a tool on a connected MCP server.

```json
{
  "type": "mcp_tool",
  "server": "my-server",
  "tool": "validate",
  "arguments": { "key": "value" }
}
```

Server must already be connected. Tool result body parsed as output JSON.

## `prompt` (LLM judgment)

Single-turn LLM call. No tools.

```json
{
  "type": "prompt",
  "prompt": "Return {\"ok\": false, \"reason\": ...} if any TODO comments were added.",
  "model": "claude-haiku-4-5-20251001",
  "timeout": 30
}
```

Response shape:

```json
{ "ok": true }
{ "ok": false, "reason": "tests still failing" }
```

`ok: false` blocks the event; `reason` feeds back to Claude. Default model: Haiku. Use when judgment beats deterministic rules but you don't need file reads.

## `agent` (experimental)

Spawn a subagent with tools. Multi-turn verification.

```json
{
  "type": "agent",
  "prompt": "Run the test suite and verify all unit tests pass. $ARGUMENTS",
  "timeout": 120
}
```

- Default timeout 60s. Up to 50 tool-use turns.
- Same `{"ok": bool, "reason": str}` response.
- Use when verification needs file reads / grep / shell. Behavior may change.

## When to pick which

| Need | Type |
|---|---|
| Format files, log audits, run linters, gate by string match | `command` |
| Hand off to existing web service / cloud function | `http` |
| Reuse existing MCP server logic | `mcp_tool` |
| "Did the user describe what they actually want?" type judgment, no file inspection | `prompt` |
| "Do tests pass?" / "Does code conform to style guide?" with file inspection | `agent` |

For production: prefer `command` or `http`. `agent` is experimental.
