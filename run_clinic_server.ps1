# Fayz Medical House - Universal PowerShell Server Runner
param(
    [int]$Port = 3000
)

$BaseDir = $PSScriptRoot
if (-not $BaseDir) { $BaseDir = (Get-Location).Path }

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 🏥 Fayz Medical House — Web & API Server Launcher" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Base Directory: $BaseDir" -ForegroundColor Gray

# Look for Python
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    $PythonExe = (Get-Command py -ErrorAction SilentlyContinue).Source
}
if (-not $PythonExe) {
    $PythonCandidates = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python", "C:\Python*", "C:\Program Files\Python*" -Filter "python.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    if ($PythonCandidates) {
        $PythonExe = $PythonCandidates[0]
    }
}

if ($PythonExe) {
    Write-Host " [✓] Python detected: $PythonExe" -ForegroundColor Green
    Write-Host " Starting Python SQLite REST API Server (server.py) on Port $Port..." -ForegroundColor Cyan
    & $PythonExe "$BaseDir\server.py"
    exit
}

Write-Host " [i] Python not detected in PATH. Starting Native PowerShell HTTP Listener on Port $Port..." -ForegroundColor Yellow

$Listener = New-Object System.Net.HttpListener
$Prefix = "http://localhost:$Port/"
$Listener.Prefixes.Add($Prefix)

try {
    $Listener.Start()
} catch {
    Write-Host " [!] Port $Port might be busy. Trying Port 3001..." -ForegroundColor Red
    $Port = 3001
    $Prefix = "http://localhost:$Port/"
    $Listener = New-Object System.Net.HttpListener
    $Listener.Prefixes.Add($Prefix)
    $Listener.Start()
}

Write-Host " [✓] Fayz Medical House Server is LIVE at: $Prefix" -ForegroundColor Green
Write-Host "     - Main Website:        ${Prefix}index.html" -ForegroundColor Cyan
Write-Host "     - Super-Portal:        ${Prefix}superpage.html" -ForegroundColor Cyan
Write-Host "     - Doctor Post & EMR:   ${Prefix}doctor.html" -ForegroundColor Cyan
Write-Host "     - Inpatient (14 Beds): ${Prefix}building_management.html" -ForegroundColor Cyan
Write-Host "     - Accounting & POS:    ${Prefix}accounting.html" -ForegroundColor Cyan
Write-Host "     - HR & Duty Roster:    ${Prefix}hr.html" -ForegroundColor Cyan
Write-Host "     - Reception Desk:      ${Prefix}reception.html" -ForegroundColor Cyan
Write-Host "     - Patient CRM:         ${Prefix}crm.html" -ForegroundColor Cyan
Write-Host "     - Medical Blank (A4):  ${Prefix}medical_blank.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Gray

$MIMETypes = @{
    ".html" = "text/html; charset=utf-8"
    ".htm"  = "text/html; charset=utf-8"
    ".css"  = "text/css; charset=utf-8"
    ".js"   = "application/javascript; charset=utf-8"
    ".json" = "application/json; charset=utf-8"
    ".png"  = "image/png"
    ".jpg"  = "image/jpeg"
    ".jpeg" = "image/jpeg"
    ".svg"  = "image/svg+xml"
    ".ico"  = "image/x-icon"
    ".xlsx" = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ".txt"  = "text/plain; charset=utf-8"
}

while ($Listener.IsListening) {
    $Context = $Listener.GetContext()
    $Request = $Context.Request
    $Response = $Context.Response

    # CORS Headers
    $Response.Headers.Add("Access-Control-Allow-Origin", "*")
    $Response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    $Response.Headers.Add("Access-Control-Allow-Headers", "Content-Type, Authorization")

    if ($Request.HttpMethod -eq "OPTIONS") {
        $Response.StatusCode = 200
        $Response.Close()
        continue
    }

    $RawUrl = [System.Uri]::UnescapeDataString($Request.Url.AbsolutePath)
    if ($RawUrl -eq "/" -or $RawUrl -eq "") {
        $RawUrl = "/index.html"
    }

    # Handle /api/ requests with json fallbacks
    if ($RawUrl.StartsWith("/api/")) {
        $Response.ContentType = "application/json; charset=utf-8"
        $ApiData = "{}"
        if ($RawUrl -match "^/api/hr") {
            $JsonPath = Join-Path $BaseDir "data\hr_db.json"
            if (Test-Path $JsonPath) { $ApiData = Get-Content $JsonPath -Raw -Encoding UTF8 }
        } elseif ($RawUrl -match "^/api/reception") {
            $JsonPath = Join-Path $BaseDir "data\reception_db.json"
            if (Test-Path $JsonPath) { $ApiData = Get-Content $JsonPath -Raw -Encoding UTF8 }
        } elseif ($RawUrl -match "^/api/accounting") {
            $JsonPath = Join-Path $BaseDir "data\accounting_db.json"
            if (Test-Path $JsonPath) { $ApiData = Get-Content $JsonPath -Raw -Encoding UTF8 }
        } elseif ($RawUrl -match "^/api/beds") {
            $JsonPath = Join-Path $BaseDir "data\clinic_rooms.json"
            if (Test-Path $JsonPath) { $ApiData = Get-Content $JsonPath -Raw -Encoding UTF8 }
        } else {
            $ApiData = '{"status":"ok","message":"Fayz Medical House API online"}'
        }

        $Bytes = [System.Text.Encoding]::UTF8.GetBytes($ApiData)
        $Response.ContentLength64 = $Bytes.Length
        $Response.StatusCode = 200
        $Response.OutputStream.Write($Bytes, 0, $Bytes.Length)
        $Response.Close()
        continue
    }

    $LocalPath = Join-Path $BaseDir ($RawUrl.TrimStart('/'))

    if (Test-Path $LocalPath -PathType Leaf) {
        $Ext = [System.IO.Path]::GetExtension($LocalPath).ToLower()
        $ContentType = "application/octet-stream"
        if ($MIMETypes.ContainsKey($Ext)) {
            $ContentType = $MIMETypes[$Ext]
        }
        $Response.ContentType = $ContentType

        try {
            $FileBytes = [System.IO.File]::ReadAllBytes($LocalPath)
            $Response.ContentLength64 = $FileBytes.Length
            $Response.StatusCode = 200
            $Response.OutputStream.Write($FileBytes, 0, $FileBytes.Length)
        } catch {
            $Response.StatusCode = 500
        }
    } else {
        $Response.StatusCode = 404
        $ErrorMsg = [System.Text.Encoding]::UTF8.GetBytes("<h1>404 Not Found</h1><p>File not found: $RawUrl</p>")
        $Response.ContentType = "text/html; charset=utf-8"
        $Response.ContentLength64 = $ErrorMsg.Length
        $Response.OutputStream.Write($ErrorMsg, 0, $ErrorMsg.Length)
    }

    $Response.Close()
}
