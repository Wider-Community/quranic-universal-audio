# PostToolUse hook: format + lint-fix frontend files after Claude edits.
# Reads PostToolUse JSON on stdin, extracts tool_input.file_path, formats if
# it's a frontend source file. Silent no-op for non-matching files.

$raw = [Console]::In.ReadToEnd()
if (-not $raw) { exit 0 }

try { $data = $raw | ConvertFrom-Json } catch { exit 0 }

$file = $data.tool_input.file_path
if (-not $file) { $file = $data.tool_input.notebook_path }
if (-not $file) { exit 0 }
if (-not (Test-Path $file)) { exit 0 }
if ($file -notmatch 'inspector[/\\]frontend[/\\]src[/\\].*\.(ts|js|svelte)$') { exit 0 }

$frontend = Join-Path $env:CLAUDE_PROJECT_DIR 'inspector\frontend'
Push-Location $frontend
try {
    & ".\node_modules\.bin\prettier" --write --log-level=warn $file 2>&1 | Out-Null
    & ".\node_modules\.bin\eslint_d" --fix $file 2>&1 | Out-Null
} finally {
    Pop-Location
}

exit 0
