# Abre una ventana de PowerShell por agente (gateway A2A), de uno en uno: espera a que cada agente responda
# antes de arrancar el siguiente (si no, los gateways se niegan a arrancar a la vez). Salta los que ya responden.
# Uso: .\scripts\start_agents.ps1
$agents = [ordered]@{ deteccion = 9901; mitigacion = 9902; documentacion = 9903; unico = 9904 }

function Test-Agent([int]$port) {
    try { (Invoke-WebRequest "http://127.0.0.1:$port/.well-known/agent-card.json" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false }
}

foreach ($p in $agents.Keys) {
    $port = $agents[$p]
    if (-not (Test-Path (Join-Path $env:LOCALAPPDATA "hermes\profiles\$p"))) { Write-Host "[$p] perfil inexistente, se omite"; continue }
    if (Test-Agent $port) { Write-Host "[$p] ya responde en $port, se omite"; continue }
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='hermes-$p'; hermes -p $p gateway run"
    Write-Host "[$p] iniciando, esperando respuesta en $port ..." -NoNewline
    $ok = $false
    for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Seconds 3; if (Test-Agent $port) { $ok = $true; break } }
    if ($ok) { Write-Host " OK" -ForegroundColor Green }
    else { Write-Host " NO RESPONDE en 2 min: revisa la ventana hermes-$p" -ForegroundColor Red }
}
Write-Host "`nEstado final:"
foreach ($p in $agents.Keys) { "{0,-14} {1}" -f $p, $(if (Test-Agent $agents[$p]) { "OK" } else { "caído" }) }
