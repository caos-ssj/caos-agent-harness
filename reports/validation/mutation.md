# Pruebas de mutación (pipeline de validación, tablero y router)

Detectadas: **26/26**

| Mutación | Resultado |
|---|---|
| umbral de confianza a 0 | detectada |
| un solo reintento | detectada |
| sin espera entre reintentos | detectada |
| cambio de esquema solo mira label | detectada |
| sin validar etiqueta | detectada |
| calidad de datos desactivada | detectada |
| backoff constante | detectada |
| ignora retry_after | detectada |
| agotado marca rejected | detectada |
| acepta cualquier confianza | detectada |
| confianza baja responde igual | detectada |
| tablero: envía a un agente ocupado | detectada |
| tablero: reclamación sin condición (dos envíos del mismo encargo) | detectada |
| tablero: un envío fallido pierde el encargo | detectada |
| tablero: un envío sin confirmar se da por enviado | detectada |
| tablero: caracteres de control llegan al agente | detectada |
| tablero: se revisa lo que aún no se entregó | detectada |
| tablero: una entrega devuelta sigue contando | detectada |
| tablero: la devolución no lleva la nota del revisor | detectada |
| router: usa la precisión puntual en vez del límite inferior | detectada |
| router: elige el más caro | detectada |
| router: si nadie cumple, elige igualmente | detectada |
| router: acepta un sistema que no responde nada | detectada |
| router: ignora la cobertura mínima | detectada |
| router: se queda con la medición más vieja | detectada |
| router: ignora el límite de latencia | detectada |
