# Close a Steam game after Sunshine/Apollo Quit App (/cancel).
# AppID stays a string — never cast to [int] (Non-Steam 64-bit rungameids overflow).
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$AppId,
    [switch]$Watch,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
if ($AppId -notmatch '^\d+$') {
    Write-Output "gamesphere-steam-close: invalid app id: $AppId"
    exit 1
}

$ForegroundSec = 8
if ($env:GAMESPHERE_CLOSE_FOREGROUND_SEC) { $ForegroundSec = [double]$env:GAMESPHERE_CLOSE_FOREGROUND_SEC }
$WatchSec = 180
if ($env:GAMESPHERE_CLOSE_WATCH_SEC) { $WatchSec = [double]$env:GAMESPHERE_CLOSE_WATCH_SEC }
$WatchPoll = 1.5
if ($env:GAMESPHERE_CLOSE_WATCH_POLL) { $WatchPoll = [double]$env:GAMESPHERE_CLOSE_WATCH_POLL }
if ($env:GAMESPHERE_CLOSE_DRYRUN) { $DryRun = $true }
$WatchMode = [bool]$Watch -or ($env:GAMESPHERE_CLOSE_WATCHER -eq "1")

$Log = Join-Path ($env:TEMP) "gamesphere-steam-close.log"

function Write-CloseLog([string]$Message) {
    $line = "gamesphere-steam-close: $Message"
    Write-Output $line
    try { Add-Content -Path $Log -Value $line -ErrorAction SilentlyContinue } catch {}
}

function Get-IdStrings([string]$Raw) {
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    [void]$set.Add($Raw)
    try {
        $n = [uint64]$Raw
        if ($n -gt 4294967295) {
            [void]$set.Add([string]($n -shr 32))
        } else {
            [void]$set.Add([string](($n -shl 32) -bor 0x02000000))
        }
    } catch {}
    return $set
}

function Get-ShortId([string]$Raw) {
    try {
        $n = [uint64]$Raw
        if ($n -gt 4294967295) { return [string]($n -shr 32) }
    } catch {}
    return $Raw
}

$Ids = Get-IdStrings $AppId
$Short = Get-ShortId $AppId

$ProtectedNames = @(
    "steam.exe", "steamwebhelper.exe", "steamservice.exe",
    "sunshine.exe", "apollo.exe", "gamesphere-steam-close"
)

function Test-Protected([string]$Name, [string]$Exe, [string]$Cmd) {
    $blob = ("$Name $Exe $Cmd").ToLowerInvariant()
    if ($blob -match "gamesphere-steam-close") { return $true }
    if ($blob -match "steamwebhelper") { return $true }
    foreach ($p in $ProtectedNames) {
        if ($Name -and $Name.Equals($p, [StringComparison]::OrdinalIgnoreCase)) { return $true }
        if ($Exe -and ($Exe.ToLowerInvariant().EndsWith("\" + $p) -or $Exe.ToLowerInvariant().EndsWith("/" + $p))) { return $true }
    }
    return $false
}

function Get-SteamLibraries {
    $libs = New-Object 'System.Collections.Generic.List[string]'
    $vdfs = New-Object 'System.Collections.Generic.List[string]'
    try {
        $steamPath = (Get-ItemProperty -Path "HKCU:\Software\Valve\Steam" -ErrorAction Stop).SteamPath
        if ($steamPath) { $vdfs.Add((Join-Path $steamPath "steamapps\libraryfolders.vdf")) }
    } catch {}
    $vdfs.Add("C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf")
    $vdfs.Add("C:\Program Files\Steam\steamapps\libraryfolders.vdf")
    foreach ($vdf in $vdfs) {
        if (-not (Test-Path -LiteralPath $vdf)) { continue }
        $text = Get-Content -LiteralPath $vdf -Raw -ErrorAction SilentlyContinue
        if (-not $text) { continue }
        [regex]::Matches($text, '"path"\s+"([^"]+)"') | ForEach-Object {
            $p = $_.Groups[1].Value -replace '\\\\', '\'
            if ($p -and (Test-Path -LiteralPath $p)) { $libs.Add($p) }
        }
        $parent = Split-Path (Split-Path $vdf -Parent) -Parent
        if ($parent) { $libs.Add($parent) }
    }
    return $libs | Select-Object -Unique
}

$GenericExes = @(
    "crashreportclient.exe", "crashpad_handler.exe", "unitycrashhandler.exe",
    "unitycrashhandler32.exe", "unitycrashhandler64.exe", "uninstall.exe",
    "vcredist_x64.exe", "vcredist_x86.exe", "vc_redist.x64.exe", "vc_redist.x86.exe",
    "dxsetup.exe", "dotnetfx.exe", "easyanticheat_setup.exe", "easyanticheat_eos_setup.exe"
)

function Test-DistinctiveExe([string]$Name) {
    $low = $Name.ToLowerInvariant()
    if ($GenericExes -contains $low) { return $false }
    $stem = [IO.Path]::GetFileNameWithoutExtension($low)
    if ($stem.StartsWith("easyanticheat")) { return $false }
    return $stem.Length -ge 10
}

function Get-GameRoots {
    $prefixes = New-Object 'System.Collections.Generic.List[string]'
    $exes = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($lib in Get-SteamLibraries) {
        $steamapps = Join-Path $lib "steamapps"
        foreach ($aid in $Ids) {
            $acf = Join-Path $steamapps ("appmanifest_{0}.acf" -f $aid)
            if (Test-Path -LiteralPath $acf) {
                $txt = Get-Content -LiteralPath $acf -Raw -ErrorAction SilentlyContinue
                $m = [regex]::Match([string]$txt, '"installdir"\s+"([^"]+)"')
                if ($m.Success) {
                    $common = Join-Path $steamapps (Join-Path "common" $m.Groups[1].Value)
                    if (Test-Path -LiteralPath $common) {
                        $prefixes.Add($common)
                        Get-ChildItem -LiteralPath $common -Filter *.exe -File -ErrorAction SilentlyContinue | ForEach-Object {
                            if ($GenericExes -notcontains $_.Name.ToLowerInvariant()) { [void]$exes.Add($_.Name.ToLowerInvariant()) }
                        }
                        foreach ($rel in @("Phoenix\Binaries\Win64", "Binaries\Win64", "Win64", "Binaries", "Engine\Binaries\Win64")) {
                            $dir = Join-Path $common $rel
                            if (Test-Path -LiteralPath $dir) {
                                Get-ChildItem -LiteralPath $dir -Filter *.exe -File -ErrorAction SilentlyContinue | ForEach-Object {
                                    if ($GenericExes -notcontains $_.Name.ToLowerInvariant()) { [void]$exes.Add($_.Name.ToLowerInvariant()) }
                                }
                            }
                        }
                    }
                }
            }
            foreach ($sub in @("compatdata", "shadercache")) {
                $p = Join-Path $steamapps (Join-Path $sub $aid)
                if (Test-Path -LiteralPath $p) { $prefixes.Add($p) }
            }
        }
        foreach ($aid in @($Short, $AppId)) {
            foreach ($sub in @("compatdata", "shadercache")) {
                $p = Join-Path $steamapps (Join-Path $sub $aid)
                if (Test-Path -LiteralPath $p) { $prefixes.Add($p) }
            }
        }
    }
    return @{ Prefixes = ($prefixes | Select-Object -Unique); Exes = @($exes) }
}

$Roots = Get-GameRoots
$Prefixes = @($Roots.Prefixes)
$ExeNames = @($Roots.Exes)

function Test-Match([string]$Name, [string]$Exe, [string]$Cmd) {
    if (Test-Protected $Name $Exe $Cmd) { return $false }
    $blob = "$Name $Exe $Cmd"
    foreach ($aid in $Ids) {
        if ($blob -match [regex]::Escape("AppId=$aid")) { return $true }
        if ($blob -match [regex]::Escape("AppID=$aid")) { return $true }
        if ($blob -match [regex]::Escape("SteamAppId=$aid")) { return $true }
        if ($blob -match [regex]::Escape("SteamGameId=$aid")) { return $true }
        if ($blob -match [regex]::Escape("STEAM_COMPAT_APP_ID=$aid")) { return $true }
    }
    foreach ($prefix in $Prefixes) {
        if ($prefix -and $blob.IndexOf($prefix, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    }
    foreach ($exeName in $ExeNames) {
        if (-not (Test-DistinctiveExe $exeName)) { continue }
        if ($blob.IndexOf($exeName, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
        if ($Name -and $Name.Equals($exeName, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Get-Targets {
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $self = $PID
    $ppid = (Get-CimInstance Win32_Process -Filter "ProcessId=$self" -ErrorAction SilentlyContinue).ParentProcessId
    $roots = @()
    foreach ($p in $procs) {
        if ($p.ProcessId -eq $self -or $p.ProcessId -eq $ppid -or $p.ProcessId -lt 8) { continue }
        if (Test-Match $p.Name $p.ExecutablePath $p.CommandLine) { $roots += $p.ProcessId }
    }
    $byParent = @{}
    foreach ($p in $procs) {
        $key = [int]$p.ParentProcessId
        if (-not $byParent.ContainsKey($key)) { $byParent[$key] = New-Object 'System.Collections.Generic.List[int]' }
        [void]$byParent[$key].Add([int]$p.ProcessId)
    }
    $targets = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($root in $roots) {
        $stack = New-Object 'System.Collections.Generic.Stack[int]'
        $stack.Push([int]$root)
        $seen = New-Object 'System.Collections.Generic.HashSet[int]'
        while ($stack.Count -gt 0) {
            $cur = $stack.Pop()
            if (-not $seen.Add($cur)) { continue }
            $info = $procs | Where-Object { $_.ProcessId -eq $cur } | Select-Object -First 1
            if ($info -and (Test-Protected $info.Name $info.ExecutablePath $info.CommandLine)) { continue }
            [void]$targets.Add($cur)
            if ($byParent.ContainsKey($cur)) {
                foreach ($ch in $byParent[$cur]) { $stack.Push($ch) }
            }
        }
    }
    $ordered = @($targets) | Sort-Object {
        $info = $procs | Where-Object { $_.ProcessId -eq $_ } | Select-Object -First 1
        $cmd = [string]$info.CommandLine
        if ($cmd -match 'reaper' -and $cmd -match 'SteamLaunch') { 1 } else { 0 }
    }, { -$_ }
    return @{ Targets = @($ordered); Roots = $roots; Scanned = $procs.Count }
}

function Stop-Target([int]$ProcId) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
    $cmd = ""
    if ($info) { $cmd = ([string]$info.CommandLine).Substring(0, [Math]::Min(140, ([string]$info.CommandLine).Length)) }
    if ($DryRun) {
        Write-CloseLog "dry-run kill $ProcId $cmd"
        return
    }
    Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
}

function Invoke-Sweep([double]$Seconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    $killed = New-Object 'System.Collections.Generic.HashSet[int]'
    $lastRoots = @()
    $emptyLogged = $false
    $attempt = 0
    while ([DateTime]::UtcNow -lt $deadline) {
        $attempt += 1
        $found = Get-Targets
        $lastRoots = $found.Roots
        if (-not $found.Targets -or $found.Targets.Count -eq 0) {
            if (-not $emptyLogged) {
                Write-CloseLog "no matching processes yet (scanned $($found.Scanned)); watching"
                $emptyLogged = $true
            }
            Start-Sleep -Milliseconds 600
            continue
        }
        Write-CloseLog ("attempt {0} roots={1} targets={2}" -f $attempt, ($found.Roots -join ","), ($found.Targets -join ","))
        foreach ($pid in $found.Targets) {
            Stop-Target $pid
            [void]$killed.Add([int]$pid)
        }
        Start-Sleep -Milliseconds 450
        foreach ($pid in $found.Targets) {
            if (Get-Process -Id $pid -ErrorAction SilentlyContinue) { Stop-Target $pid }
        }
        $left = Get-Targets
        if (-not $left.Targets -or $left.Targets.Count -eq 0) { break }
        Start-Sleep -Milliseconds 200
    }
    return @{ Killed = $killed; Roots = $lastRoots }
}

Write-CloseLog ("request id={0} match={1} roots={2} exes={3}{4}" -f $AppId, (($Ids | Sort-Object) -join ","), ($Prefixes -join "|"), (($ExeNames | Select-Object -First 12) -join ","), $(if ($WatchMode) { " watch" } else { "" }))

if ($WatchMode) {
    $result = Invoke-Sweep $WatchSec
    $left = Get-Targets
    if ($left.Targets -and $left.Targets.Count -gt 0) {
        Write-CloseLog ("watcher still running: {0}" -f ($left.Targets -join ","))
        exit 1
    }
    Write-CloseLog ("watcher done killed_n={0} last_roots={1}" -f $result.Killed.Count, ($result.Roots -join ","))
    exit 0
}

$result = Invoke-Sweep $ForegroundSec
$left = Get-Targets
if (-not $WatchMode) {
    $self = $MyInvocation.MyCommand.Path
    if ($self -and -not $DryRun) {
        $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", $self, $AppId, "-Watch")
        $env:GAMESPHERE_CLOSE_WATCHER = "1"
        Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WindowStyle Hidden | Out-Null
        Write-CloseLog ("spawned late-spawn watcher for {0}s" -f [int]$WatchSec)
    } elseif ($DryRun) {
        Write-CloseLog "dry-run would spawn watcher"
    }
}
Write-CloseLog ("done killed_n={0} last_roots={1} leftover={2}" -f $result.Killed.Count, ($result.Roots -join ","), ($(if ($left.Targets) { $left.Targets -join "," } else { "" })))
exit 0
