# Babel's Library: reach phones and e-readers plugged in over USB (MTP), which Windows shows under "This PC"
# but which have no drive letter. Uses the Windows Shell, the same way File Explorer does.
param([string]$ConfigPath)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$shell = New-Object -ComObject Shell.Application

function Out-Json($o) { [Console]::Out.WriteLine(($o | ConvertTo-Json -Compress -Depth 4)); [Console]::Out.Flush() }

function FileName($it) {
    $n = $null
    try { $n = $it.ExtendedProperty("System.FileName") } catch {}
    if (-not $n) { $n = $it.Name }
    return $n
}

function Resolve-ShellFolder([string]$path) {
    $p = $path.Trim().TrimEnd('\')
    if ($p.StartsWith("::")) { return $shell.Namespace($p) }
    $parts = $p -split '\\' | Where-Object { $_ -ne "" }
    $folder = $shell.Namespace(17)   # This PC
    $start = 0
    if ($parts.Count -gt 0 -and @("This PC", "Computer", "My Computer") -contains $parts[0]) { $start = 1 }
    for ($i = $start; $i -lt $parts.Count; $i++) {
        $next = $null
        foreach ($it in $folder.Items()) {
            if ($it.IsFolder -and ($it.Name -ieq $parts[$i])) { $next = $it.GetFolder; break }
        }
        if (-not $next) { throw "Couldn't find '$($parts[$i])'. Is the device plugged in and unlocked?" }
        $folder = $next
    }
    return $folder
}

$exts = @($cfg.exts)
function Walk($folder, [string]$rel) {
    foreach ($it in $folder.Items()) {
        if ($it.IsFolder) {
            if ($it.Name.StartsWith(".")) { continue }
            Walk $it.GetFolder ($(if ($rel) { "$rel\$($it.Name)" } else { $it.Name }))
        } else {
            $fn = FileName $it
            $ext = [System.IO.Path]::GetExtension($fn).ToLower()
            if ($exts -contains $ext -and -not $fn.StartsWith(".")) {
                [pscustomobject]@{ rel = $(if ($rel) { "$rel\$fn" } else { $fn }); size = [int64]$it.Size; item = $it }
            }
        }
    }
}

try {
    switch ($cfg.mode) {
        "browse" {
            $out = @()
            if (-not $cfg.path) {
                foreach ($it in $shell.Namespace(17).Items()) {
                    if ($it.IsFolder) { $out += [pscustomobject]@{ name = $it.Name; device = -not $it.IsFileSystem } }
                }
            } else {
                $f = Resolve-ShellFolder $cfg.path
                foreach ($it in $f.Items()) { if ($it.IsFolder -and -not $it.Name.StartsWith(".")) { $out += [pscustomobject]@{ name = $it.Name; device = $true } } }
            }
            Out-Json @{ ok = $true; folders = @($out) }
        }
        "list" {
            $f = Resolve-ShellFolder $cfg.path
            $files = @(Walk $f "" | ForEach-Object { [pscustomobject]@{ rel = $_.rel; size = $_.size } })
            Out-Json @{ ok = $true; files = $files }
        }
        "copy" {
            $f = Resolve-ShellFolder $cfg.path
            $files = @(Walk $f "")
            Out-Json @{ total = $files.Count }
            foreach ($x in $files) {
                $destDir = Join-Path $cfg.dest ([System.IO.Path]::GetDirectoryName($x.rel))
                New-Item -ItemType Directory -Force -Path $destDir | Out-Null
                $target = Join-Path $destDir ([System.IO.Path]::GetFileName($x.rel))
                $ok = $false
                try {
                    $shell.Namespace($destDir).CopyHere($x.item, 4 + 16 + 512 + 1024)
                    # copying from a device finishes in the background; wait until the whole file has arrived
                    $limit = (Get-Date).AddSeconds(30 + $x.size / 2MB)
                    while ((Get-Date) -lt $limit) {
                        if (Test-Path -LiteralPath $target) {
                            $len = (Get-Item -LiteralPath $target).Length
                            if ($len -ge $x.size -and $len -gt 0) { $ok = $true; break }
                        }
                        Start-Sleep -Milliseconds 150
                    }
                } catch {}
                Out-Json @{ rel = $x.rel; ok = $ok; path = $target }
            }
            Out-Json @{ finished = $true }
        }
    }
} catch {
    Out-Json @{ ok = $false; error = $_.Exception.Message }
}
