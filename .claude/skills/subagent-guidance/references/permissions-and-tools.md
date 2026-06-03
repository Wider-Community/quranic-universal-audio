# Permissions and Tools

## Tool resolution

- Default: subagent inherits ALL tools from parent (including MCP).
- `tools` is an allowlist. `disallowedTools` is a denylist.
- If both set: `disallowedTools` applied first, then `tools` resolves against the remainder. A tool in both is removed.

```yaml
# Allowlist only
tools: Read, Grep, Glob, Bash
```

```yaml
# Inherit all except writes
disallowedTools: Write, Edit
```

## Restricting Agent spawning (main-thread only)

When an agent runs as the main session via `claude --agent`, it can spawn subagents using the Agent tool. Restrict which types:

```yaml
tools: Agent(worker, researcher), Read, Bash
```

Allowlist semantics. Unlisted types fail and are hidden from the agent's prompt. Use `permissions.deny` in settings to block specific agents while allowing others.

`Agent` without parentheses → unrestricted spawning. `Agent` omitted entirely → cannot spawn any subagents.

This restriction has no effect inside subagent definitions, since subagents cannot spawn subagents.

(Note: pre-2.1.63 the tool was `Task`. `Task(...)` still works as alias.)

## Permission modes

| Mode | Behavior |
|---|---|
| `default` | Standard prompts |
| `acceptEdits` | Auto-accept edits + common filesystem commands within cwd / `additionalDirectories` |
| `auto` | Background classifier reviews commands and protected-dir writes |
| `dontAsk` | Auto-deny prompts (allowed tools still work) |
| `bypassPermissions` | Skip all prompts. Risky — allows writes to `.git`, `.claude`, `.vscode`, etc. Root/home `rm -rf` still prompts. |
| `plan` | Read-only exploration |

### Inheritance precedence

- Parent `bypassPermissions` or `acceptEdits` → takes precedence, child cannot override.
- Parent `auto` → child inherits auto, child's `permissionMode` ignored, classifier evaluates child's calls with parent's rules.

## Disabling subagents

In settings, `permissions.deny`:

```json
{
  "permissions": {
    "deny": ["Agent(Explore)", "Agent(my-custom-agent)"]
  }
}
```

Or CLI: `claude --disallowedTools "Agent(Explore)"`.

Works for built-in and custom alike.

## Conditional rules via PreToolUse hooks

When tool-level allow/deny is too coarse (e.g., allow `Bash` but only read-only SQL), use a `PreToolUse` hook. See `hooks.md` and `examples.md` (db-reader example).
