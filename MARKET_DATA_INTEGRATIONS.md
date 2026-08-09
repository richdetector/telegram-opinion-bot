# Radar Market Data Integrations

Radar ya separa noticias, verificacion, scoring de impacto y senales de mercado.

La version actual no inventa datos de mercado. Si una senal no esta disponible en las fuentes actuales, queda como `Unknown` y no se utiliza para justificar una publicacion.

## Integraciones necesarias

### Precio y volumen

- Fuente ideal: exchange APIs liquidas o proveedor agregado.
- Alternativas gratuitas: Binance/Coinbase/Kraken public APIs para BTC/ETH spot.
- Riesgo: una sola sede no representa todo el mercado.

### Derivados

- Datos necesarios: open interest, funding, basis, liquidaciones, opciones, put/call, term structure.
- Proveedores habituales: Coinglass, Laevitas, Deribit, Binance Futures, CME.
- Nota: muchas fuentes completas son de pago. Sin API fiable, Radar no debe inferir posicionamiento profesional.

### ETF flows

- Datos necesarios: inflows/outflows diarios BTC/ETH, acumulado, media 7d, aceleracion/desaceleracion.
- Fuentes posibles: emisores, bolsas, gestores de datos ETF, agregadores especializados.
- Regla: distinguir un evento de un dia de un cambio persistente de regimen.

### On-chain

- Datos necesarios: exchange netflows, whale transfers, miner flows, MVRV, SOPR, NUPL, realized cap, dormant coins, stablecoin liquidity.
- Proveedores habituales: Glassnode, CryptoQuant, Coin Metrics, Arkham, Whale Alert.
- Nota: varias fuentes son de pago o tienen limites severos.

### Whale intelligence

- Datos necesarios: wallet labels, exchange/custodian/miner/ETF tags, direction, probable deposit/withdrawal/internal transfer.
- Proveedores habituales: Arkham, Nansen, Chainalysis, Whale Alert.
- Regla: una transferencia aislada no debe producir alerta importante.

### Order book / liquidez

- Datos necesarios: profundidad, clusters de ordenes, cambios de liquidez, liquidation maps.
- Proveedores habituales: exchanges, Bookmap, Hyblock, Coinglass.
- Nota: los mapas de liquidez son estimaciones, no certezas.

### Sentimiento

- Datos necesarios: Reddit, Telegram, X/Twitter si hay API legal, titulares, busquedas/tendencias.
- Estado actual: Reddit RSS se ha retirado del feed activo porque devuelve 429 de forma recurrente.
- Integracion robusta recomendada: API oficial o proveedor con rate limits claros.

## Capas de certeza

Cada senal debe clasificarse como:

- `OBSERVED`: dato directamente observado.
- `CALCULATED`: calculado sobre datos observados.
- `INFERRED`: inferencia razonable.
- `SPECULATIVE`: posibilidad no confirmada.

Radar no debe mezclar estas capas ni convertirlas en recomendaciones de trading.
