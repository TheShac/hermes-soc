# Verifica que el banco de pruebas está sano. Uso: .\scripts\check_testbed.ps1
$root = Split-Path -Parent $PSScriptRoot
$fail = 0

function Check([string]$name, [scriptblock]$test) {
    try { $ok = & $test } catch { $ok = $false }
    if ($ok) { Write-Host "[OK]    $name" -ForegroundColor Green }
    else     { Write-Host "[FALLA] $name" -ForegroundColor Red; $script:fail++ }
}

function Login([string]$pw) {
    $b = @{ username = "admin"; password = $pw } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri http://localhost:8000/login -ContentType "application/json" -Body $b
}

Check "target /health" { (Invoke-RestMethod http://localhost:8000/health).status -eq "ok" }
Check "target /api/data (usa Redis)" { (Invoke-RestMethod http://localhost:8000/api/data).hits -gt 0 }
Check "login correcto -> token" { (Login "S3cret-testbed").token -eq "demo-token" }
Check "login incorrecto -> 401" {
    try { Login "mala" | Out-Null; $false } catch { $_.Exception.Response.StatusCode.value__ -eq 401 }
}
Check "Prometheus ve el job 'target' en estado up" {
    $t = Invoke-RestMethod http://localhost:9090/api/v1/targets
    ($t.data.activeTargets | Where-Object { $_.labels.job -eq "target" }).health -eq "up"
}
Check "Prometheus tiene la métrica http_requests_total" {
    (Invoke-RestMethod "http://localhost:9090/api/v1/query?query=http_requests_total").data.result.Count -gt 0
}
Check "log de acceso JSON existe y tiene líneas" {
    $f = Join-Path $root "testbed\logs\access.jsonl"
    (Test-Path $f) -and ((Get-Content $f -Tail 1) | ConvertFrom-Json).status -gt 0
}
Check "tráfico legítimo activo (soc-legit)" {
    $l = docker logs --tail 1 soc-legit 2>&1
    ($l | ConvertFrom-Json).ok -gt 0
}
Check "redis responde" { (docker exec soc-redis redis-cli ping) -eq "PONG" }
Check "target: tc disponible (latencia)" { docker exec soc-target tc qdisc show dev eth0 *> $null; $LASTEXITCODE -eq 0 }
Check "target: iptables disponible (block_ip)" { docker exec soc-target iptables -L -n *> $null; $LASTEXITCODE -eq 0 }
Check "target: stress-ng disponible (falla de memoria)" { docker exec soc-target stress-ng --version *> $null; $LASTEXITCODE -eq 0 }

if ($fail -eq 0) { Write-Host "`nBanco de pruebas OK" -ForegroundColor Green }
else { Write-Host "`n$fail comprobación(es) fallaron" -ForegroundColor Red; exit 1 }
