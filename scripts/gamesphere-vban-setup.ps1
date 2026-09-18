# GameSphere mic → PC (Windows): VB-CABLE + OSS VBAN feeder.
# Protocol: VBAN stream name GameSphere, UDP 6980.
# Does NOT bundle VB-CABLE — downloads the official zip after the user accepts
# VB-Audio donationware terms. Does NOT install VoiceMeeter.
# Does not change GameSphere iOS.
#
# Actions:
#   info       Print LAN IPs + defaults (no changes)
#   setup      Install VB-CABLE if needed + firewall + status card
#   install    Download/run VB-CABLE setup only (requires -AcceptLicense)
#   firewall   Allow UDP 6980 inbound
#   open-docs  Open MIC-TO-PC docs

param(
    [ValidateSet("info", "setup", "install", "firewall", "open-docs")]
    [string]$Action = "info",
    [switch]$AcceptLicense
)

$ErrorActionPreference = "Continue"
$StreamName = if ($env:GAMESPHERE_VBAN_STREAM) { $env:GAMESPHERE_VBAN_STREAM } else { "GameSphere" }
$Port = if ($env:GAMESPHERE_VBAN_PORT) { [int]$env:GAMESPHERE_VBAN_PORT } else { 6980 }

$OfficialPage = "https://vb-audio.com/Cable/"
$CableUrls = @(
    "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip",
    "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip"
)

function Get-LanIPv4 {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Sort-Object -Property InterfaceMetric, IPAddress |
        Select-Object -ExpandProperty IPAddress -Unique
}

function Write-Card {
    Write-Host ""
    Write-Host "=== GameSphere Mic to PC ==="
    Write-Host "Stream name : $StreamName"
    Write-Host "UDP port    : $Port"
    Write-Host "LAN IP(s)   :"
    $ips = @(Get-LanIPv4)
    if ($ips.Count -eq 0) {
        Write-Host "  (none detected — check Ethernet/Wi-Fi)"
    } else {
        foreach ($ip in $ips) { Write-Host "  $ip" }
    }
    Write-Host ""
    Write-Host "In GameSphere: Settings → Send mic to PC → enter a LAN IP above."
    Write-Host "Then stream → Mic chip on. Discord/OBS microphone: CABLE Output."
    Write-Host ""
}

function Test-VBCable {
    $names = @(
        Get-PnpDevice -ErrorAction SilentlyContinue |
            Where-Object { $_.FriendlyName -match 'VB-Audio Virtual Cable|CABLE Input|CABLE Output' } |
            Select-Object -ExpandProperty FriendlyName
    )
    if ($names.Count -gt 0) { return $true }
    foreach ($root in @("$env:ProgramFiles\VB\CABLE", "${env:ProgramFiles(x86)}\VB\CABLE")) {
        if (Test-Path $root) { return $true }
    }
    $uninst = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($path in $uninst) {
        $hit = Get-ItemProperty $path -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -match 'VB-Audio Virtual Cable|VB-CABLE' }
        if ($hit) { return $true }
    }
    return $false
}

function Ensure-Firewall {
    $ruleName = "GameSphere VBAN Mic (UDP $Port)"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "==> Firewall rule already present: $ruleName"
        return
    }
    try {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Protocol UDP `
            -LocalPort $Port `
            -Action Allow `
            -Profile Any `
            -ErrorAction Stop | Out-Null
        Write-Host "==> Added firewall rule: $ruleName"
    } catch {
        Write-Host "WARNING: Could not add firewall rule (try Run as administrator): $_"
        Write-Host "         Manually allow UDP $Port inbound if the phone cannot connect."
    }
}

function Install-VBCable {
    if (-not $AcceptLicense) {
        Write-Host "ERROR: VB-CABLE is VB-Audio donationware. Pass -AcceptLicense after the user accepts terms."
        Write-Host "Download page: $OfficialPage"
        return 2
    }

    if (Test-VBCable) {
        Write-Host "==> VB-CABLE already installed."
        return 0
    }

    Write-Host "==> Downloading VB-CABLE from VB-Audio (donationware, not bundled)…"
    Write-Host "    License / donations: $OfficialPage"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $work = Join-Path $env:TEMP ("GameSphere-VBCABLE-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    $zipPath = Join-Path $work "VBCABLE.zip"
    $got = $false
    foreach ($url in $CableUrls) {
        try {
            Write-Host "    GET $url"
            Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -TimeoutSec 120
            if ((Test-Path $zipPath) -and ((Get-Item $zipPath).Length -gt 10000)) {
                $got = $true
                break
            }
        } catch {
            Write-Host "    download failed: $_"
        }
    }
    if (-not $got) {
        Write-Host "WARNING: Could not download VB-CABLE. Opening $OfficialPage"
        Start-Process $OfficialPage
        return 1
    }

    $extract = Join-Path $work "extract"
    Expand-Archive -Path $zipPath -DestinationPath $extract -Force
    $setupName = if ([Environment]::Is64BitOperatingSystem) { "VBCABLE_Setup_x64.exe" } else { "VBCABLE_Setup.exe" }
    $setup = Get-ChildItem -Path $extract -Recurse -Filter $setupName -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $setup) {
        $setup = Get-ChildItem -Path $extract -Recurse -Filter "VBCABLE_Setup*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $setup) {
        Write-Host "ERROR: Setup exe not found in VB-CABLE zip."
        Start-Process $OfficialPage
        return 1
    }

    Write-Host "==> Running $($setup.Name) -i -h (Windows may still show a driver-trust prompt)…"
    $p = Start-Process -FilePath $setup.FullName -ArgumentList "-i","-h" -Wait -PassThru -WorkingDirectory $setup.DirectoryName
    $code = 0
    if ($p) { $code = $p.ExitCode }
    Start-Sleep -Seconds 2
    if (Test-VBCable) {
        Write-Host "==> VB-CABLE is present. A reboot is often required before CABLE Input appears."
        if ($code -eq 3010 -or $code -eq 1641) { return 3010 }
        return 0
    }
    Write-Host "WARNING: VB-CABLE not detected yet (exit $code). Reboot, or install from $OfficialPage and re-run setup."
    if ($code -eq 0) { return 3010 }
    return $code
}

function Write-StatusHtml {
    $ips = @(Get-LanIPv4)
    $primary = if ($ips.Count -gt 0) { $ips[0] } else { "0.0.0.0" }
    $dir = Join-Path $env:LOCALAPPDATA "GameSphere"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $htmlPath = Join-Path $dir "mic-to-pc.html"
    $ipList = ($ips | ForEach-Object { "<li><code>$_</code></li>" }) -join "`n"
    if (-not $ipList) { $ipList = "<li>(no LAN IP detected)</li>" }
    $html = @"
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>GameSphere Mic to PC</title>
<style>
 body{font-family:Segoe UI,system-ui,sans-serif;background:#111;color:#eee;max-width:40rem;margin:2rem auto;padding:0 1rem}
 h1{color:#e85d4c} code{background:#222;padding:.15rem .4rem;border-radius:4px;font-size:1.25rem}
 .big{font-size:2rem;font-weight:700;letter-spacing:.02em}
</style></head><body>
<h1>Mic to PC ready</h1>
<p>In GameSphere → <b>Send mic to PC</b>, enter:</p>
<p class="big"><code>$primary</code></p>
<p>Port <code>$Port</code> · stream <code>$StreamName</code></p>
<ul>$ipList</ul>
<p>Discord / OBS microphone: <b>CABLE Output</b> (VB-Audio Virtual Cable).</p>
<p>Companion Tool’s VBAN feeder plays the phone into <b>CABLE Input</b>. Keep the feeder running (it starts at logon after setup). Allow UDP $Port if the firewall prompts.</p>
<p>If CABLE Output is missing, reboot once after installing VB-CABLE.</p>
</body></html>
"@
    Set-Content -Path $htmlPath -Value $html -Encoding UTF8
    try { Start-Process $htmlPath } catch { }
    Write-Host "==> Status card: $htmlPath"
}

switch ($Action) {
    "open-docs" {
        $doc = Join-Path $PSScriptRoot "..\docs\MIC-TO-PC.md"
        if (Test-Path $doc) { Start-Process $doc }
        else { Start-Process "https://github.com/trevlars/GameSphere-Companion-Tool/blob/main/docs/MIC-TO-PC.md" }
        break
    }
    "info" {
        Write-Card
        if (Test-VBCable) { Write-Host "VB-CABLE: found" }
        else { Write-Host "VB-CABLE: not installed (run: -Action setup -AcceptLicense)" }
        Write-Host "Discord microphone: CABLE Output"
        break
    }
    "firewall" {
        Ensure-Firewall
        Write-Card
        break
    }
    "install" {
        $rc = Install-VBCable
        exit $rc
    }
    "setup" {
        Write-Host "=== GameSphere Mic to PC — automatic setup ==="
        Write-Host "Uses VB-CABLE (VB-Audio donationware) + Companion Tool’s VBAN feeder."
        Write-Host "Does not install VoiceMeeter."
        Write-Host ""
        $rc = Install-VBCable
        if ($rc -eq 2) { exit 2 }
        Ensure-Firewall
        Write-StatusHtml
        Write-Card
        if (-not (Test-VBCable)) {
            Write-Host "Install VB-CABLE from the page that opened, reboot, then run setup again."
            exit 1
        }
        if ($rc -eq 3010) {
            Write-Host "VB-CABLE installed. Reboot Windows so CABLE Input / CABLE Output appear, then start a stream."
            exit 3010
        }
        Write-Host "Done. Enter a LAN IP above in GameSphere. Discord mic: CABLE Output."
        exit 0
    }
}
