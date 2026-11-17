# Copia hermes_profiles\<perfil>\SOUL.md al directorio del perfil de Hermes (con copia de seguridad).
$root = Split-Path -Parent $PSScriptRoot
foreach ($p in "deteccion", "mitigacion", "documentacion", "unico") {
    $dst = Join-Path $env:LOCALAPPDATA "hermes\profiles\$p\SOUL.md"
    $src = Join-Path $root "hermes_profiles\$p\SOUL.md"
    if (-not (Test-Path (Split-Path $dst))) { Write-Host "[$p] el perfil no existe, se omite"; continue }
    if (Test-Path $dst) { Copy-Item $dst "$dst.bak" -Force }
    Copy-Item $src $dst -Force
    Write-Host "[$p] SOUL.md instalado"
}
