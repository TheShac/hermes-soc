# Registra los servidores MCP en los perfiles de Hermes (agrega un bloque `mcp_servers:` al config.yaml).
# Uso: .\scripts\add_mcp_config.ps1   (hace copia .bak y no toca perfiles que ya tienen mcp_servers)
param([string]$Python = $(if (Test-Path (Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Scripts\python.exe")) { Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Scripts\python.exe" } else { (Get-Command python).Source }))
$root = Split-Path -Parent $PSScriptRoot
$py = $Python -replace '\\', '/'
$det = @{ name = "soc_detection";  script = "detection_tools.py" }
$mit = @{ name = "soc_mitigation"; script = "mitigation_tools.py" }
$map = @{ deteccion = @($det); mitigacion = @($mit); unico = @($det, $mit) }
foreach ($p in $map.Keys) {
    $cfg = Join-Path $env:LOCALAPPDATA "hermes\profiles\$p\config.yaml"
    if (-not (Test-Path $cfg)) { Write-Host "[$p] no existe $cfg"; continue }
    if (Select-String -Path $cfg -Pattern '^mcp_servers:' -Quiet) { Write-Host "[$p] ya tiene mcp_servers: editalo a mano"; continue }
    Copy-Item $cfg "$cfg.bak" -Force
    $block = "`nmcp_servers:`n"
    foreach ($s in $map[$p]) {
        $script = (Join-Path $root "mcp_servers\$($s.script)") -replace '\\', '/'
        $block += "  $($s.name):`n    command: `"$py`"`n    args: [`"$script`"]`n    timeout: 90`n"
    }
    Add-Content -Path $cfg -Value $block -Encoding ASCII
    Write-Host "[$p] agregado: $(($map[$p] | ForEach-Object { $_.name }) -join ', ')"
}
