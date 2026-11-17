# Mensajes entre agentes (A2A)

Cadena lineal: ejecutor -> Detección -> Mitigación -> Documentación. Cada salto es un `SendMessage` A2A; el ejecutor (`runner/chain.py`) lleva el JSON de un agente al siguiente.
Motivo: `a2a_call` de Hermes tiene un límite fijo de 120 s y cada agente tarda 100-200 s con el modelo local; en una prueba anidada Detección expiró y Mitigación no llegó a llamar a Documentación. Se documenta como limitación.
El texto A2A entrante se trata como dato no confiable: las reglas viven en cada `SOUL.md`, los mensajes solo llevan datos.

**detection_result** (Detección -> Mitigación)
```json
{"type":"detection_result","class":"fault|attack|healthy","subtype":"latency|memory|dependency|ddos|bruteforce|none",
 "confidence":0.9,"affected_service":"target|redis","suspect_ips":["172.28.0.101"],
 "evidence":{"rps":1145,"unique_ips":4,"p95_latency_ms":243,"error_5xx_rate":0,"login_401_rate":0,"memory_ratio":0.12,"note":"..."}}
```
**mitigation_result** (Mitigación -> Documentación)
```json
{"type":"mitigation_result","detection":{...},"actions":[{"tool":"block_ip","args":{"ip":"172.28.0.101"},"ok":true}],
 "recovered":true,"verification":{"healthy":true,"reasons":[]}}
```
**Reporte** (Documentación): Markdown en español con 4 secciones: Qué ocurrió, Cómo se detectó, Acción tomada, Prevención.
El ejecutor guarda el reporte; Documentación no necesita herramientas (queda solo con A2A).
