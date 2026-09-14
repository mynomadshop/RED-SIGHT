<# Regression for repeated repairs of Windows install directories with spaces. #>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/RedSight-Preflight.ps1')

$scratch = Join-Path ([IO.Path]::GetTempPath()) ('rs-paths-' + [guid]::NewGuid().ToString('N'))
$source = 'C:\Users\builder\RED-SIGHT'
try {
    foreach ($name in @('RedSight Test', 'RedSight $Test')) {
        $root = Join-Path $scratch $name
        New-Item -ItemType Directory -Path $root -Force | Out-Null
        $target = (Resolve-Path -LiteralPath $root).Path.TrimEnd('\')
        $manifest = @{ sourceRoot = $source } | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $root 'redsight-payload.json'), $manifest)
        $targetEscaped = $target.Replace('\', '\\')
        $targetForward = $target.Replace('\', '/')
        $before = @(
            ('plain="' + $source + '\app" current="' + $target + '\app"')
            ('escaped="' + $source.Replace('\', '\\') + '\\app" current="' + $targetEscaped + '\\app"')
            ('forward="' + $source.Replace('\', '/') + '/app" current="' + $targetForward + '/app"')
            'legacy="D:\Tools\RedSight\app"'
            'legacy_escaped="D:\\Tools\\RedSight\\app"'
            'legacy_forward="D:/Tools/RedSight/app"'
        ) -join "`n"
        $expected = @(
            ('plain="' + $target + '\app" current="' + $target + '\app"')
            ('escaped="' + $targetEscaped + '\\app" current="' + $targetEscaped + '\\app"')
            ('forward="' + $targetForward + '/app" current="' + $targetForward + '/app"')
            ('legacy="' + $target + '\app"')
            ('legacy_escaped="' + $targetEscaped + '\\app"')
            ('legacy_forward="' + $targetForward + '/app"')
        ) -join "`n"
        $file = Join-Path $root 'paths.txt'
        [IO.File]::WriteAllText($file, $before)
        $first = Repair-RsHardcodedPaths -ProjectRoot $root
        if ($first.Rewritten -ne 1 -or $first.Failed -ne 0) { throw 'Initial repair did not succeed' }
        if ([IO.File]::ReadAllText($file) -cne $expected) { throw "Repair corrupted paths for $name" }
        $check = Repair-RsHardcodedPaths -ProjectRoot $root -WhatIf
        if ($check.Rewritten -ne 0) { throw "Health check finds stale paths after repair for $name" }
        $again = Repair-RsHardcodedPaths -ProjectRoot $root
        if ($again.Rewritten -ne 0 -or [IO.File]::ReadAllText($file) -cne $expected) {
            throw "Repeated repair changed correct paths for $name"
        }
        Write-Host "PASS: $name repairs all encodings once and preserves the installed path"
    }
} finally {
    Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
}
