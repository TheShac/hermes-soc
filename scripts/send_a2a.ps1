<#
Envía un mensaje A2A (JSON-RPC SendMessage, protocolo 1.0) a un agente Hermes local.
Uso:  .\scripts\send_a2a.ps1 -Port 9901 -Text "Responde exactamente: PONG"
#>
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$Text,
    [int]$TimeoutSec = 600
)

$payload = @{
    jsonrpc = "2.0"; id = 1; method = "SendMessage"
    params  = @{ message = @{
        messageId = [guid]::NewGuid().ToString()
        role      = "ROLE_USER"
        parts     = @(@{ text = $Text })
    } }
} | ConvertTo-Json -Depth 8

$bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/" -Method Post `
    -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec $TimeoutSec
$sw.Stop()

$task = $resp.result.task
Write-Host ("Estado : " + $task.status.state)
Write-Host ("Tiempo : {0:N1} s" -f $sw.Elapsed.TotalSeconds)
Write-Host "Respuesta:"
$task.status.message.parts | ForEach-Object { Write-Host $_.text }
