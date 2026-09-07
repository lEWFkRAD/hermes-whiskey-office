param(
    [string]$Godot = $env:HERMES_GODOT_BIN,
    [switch]$ForwardPlus,
    [switch]$Compatibility,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$GodotArguments
)
$ErrorActionPreference = 'Stop'
if (-not $Godot) {
    $taskGodotCommand = Get-Command godot, godot4, Godot_v4.7.2-stable_win64.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($taskGodotCommand) { $Godot = $taskGodotCommand.Source }
}
if (-not $Godot -or -not (Test-Path -LiteralPath $Godot)) {
    throw 'Set HERMES_GODOT_BIN or pass -Godot with the path to a Godot 4 executable.'
}
$env:HERMES_DESKTOP_PREVIEW = '1'
$taskGodotArgs = @('--path', $PSScriptRoot, '--xr-mode', 'off')
if ($ForwardPlus) { $taskGodotArgs += @('--rendering-method', 'forward_plus') }
if ($Compatibility) { $taskGodotArgs += @('--rendering-method', 'gl_compatibility') }
$taskGodotArgs += $GodotArguments
& $Godot @taskGodotArgs
exit $LASTEXITCODE
