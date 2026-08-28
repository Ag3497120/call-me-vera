$ErrorActionPreference = 'Stop'

$RepoDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$MountDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$StorePath = Join-Path $MountDir '.vera_store.db'
$EnvDir = Join-Path $RepoDir '.venv312'

$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = 'py'; $PythonArgs = @('-3.12') }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = 'python'; $PythonArgs = @() }
else { throw 'Python 3.12+ is required (install Python or the Windows Python launcher).' }

if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv venv --python 3.12 $EnvDir
    & uv pip install --python (Join-Path $EnvDir 'Scripts\python.exe') ("{0}[mcp]" -f $RepoDir)
} else {
    & $Python @PythonArgs -m venv $EnvDir
    & (Join-Path $EnvDir 'Scripts\python.exe') -m pip install ("{0}[mcp]" -f $RepoDir)
}

$VeraPython = Join-Path $EnvDir 'Scripts\python.exe'
& $VeraPython -m vera.cli portable-init $MountDir

if (Get-Command codex -ErrorAction SilentlyContinue) {
    & codex mcp remove vera 2>$null
    & codex mcp add vera -- $VeraPython -m vera.cli mcp --store $StorePath
    Write-Host 'Registered Vera with Codex.'
}

$Config = [ordered]@{ command = $VeraPython; args = @('-m', 'vera.cli', 'mcp', '--store', $StorePath) }
$Standard = [ordered]@{ mcpServers = [ordered]@{ vera = $Config } }
$Standard | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $MountDir 'mcp-config.json') -Encoding UTF8

$ClaudeConfig = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'
if ((Test-Path (Join-Path $env:LOCALAPPDATA 'Programs\Claude\Claude.exe')) -or (Test-Path $ClaudeConfig)) {
    $ClaudeDir = Split-Path $ClaudeConfig
    New-Item -ItemType Directory -Force $ClaudeDir | Out-Null
    if (Test-Path $ClaudeConfig) {
        try { $Claude = Get-Content $ClaudeConfig -Raw | ConvertFrom-Json } catch { $Claude = [pscustomobject]@{} }
    } else { $Claude = [pscustomobject]@{} }
    if (-not $Claude.PSObject.Properties['mcpServers']) { $Claude | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) }
    $Claude.mcpServers | Add-Member -Force -NotePropertyName vera -NotePropertyValue ([pscustomobject]$Config)
    $Claude | ConvertTo-Json -Depth 8 | Set-Content $ClaudeConfig -Encoding UTF8
    Write-Host 'Registered Vera with Claude Desktop.'
}

Write-Host "Generic MCP configuration: $(Join-Path $MountDir 'mcp-config.json')"
Write-Host 'Restart MCP clients after setup.'
Read-Host 'Press Enter to close'
