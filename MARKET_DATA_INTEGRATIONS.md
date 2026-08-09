# Radar Market Data Integrations

Radar ya separa noticias, verificacion, scoring de impacto y senales de mercado.

La version actual no inventa datos de mercado. Si una senal no esta disponible en las fuentes actuales, queda como `Unknown` y no se utiliza para justificar una publicacion.

## Integraciones necesarias

## Primera integracion implementada

### Binance USD-M Futures public API

- Datos usados ahora: BTCUSDT price, 24h change, quote volume, hourly klines, open interest history, funding history, recent force orders/liquidations.
- Free tier: endpoints publicos sin API key.
- Rate limits: Binance aplica limites por IP y devuelve `429` si se exceden; se debe hacer backoff. Los endpoints tienen pesos distintos.
- API key: no necesaria para esta primera capa.
- Coste: gratuito.
- Calidad del dato: alta para BTCUSDT en Binance, pero representa una sede/exchange, no todo el mercado global.
- Fiabilidad: buena para precio/futuros de Binance; incompleta como proxy agregado de mercado institucional.
- Limitacion clave: liquidations y OI son Binance-centric; no sustituyen datos agregados multi-exchange.

### Opciones investigadas

#### CoinGlass

- Datos: derivados, options, ETF flows, on-chain, liquidity maps, order book, whale/large position metrics.
- Free tier/API key: requiere cuenta/API key para API V4; muchas metricas avanzadas dependen del plan.
- Coste: producto profesional; documentacion publica menciona planes de pago.
- Calidad: muy buena para datos agregados de derivados/liquidez, mas completa que un exchange aislado.
- Decision: no se integra aun para evitar activar dependencia de pago/API key en esta fase.

#### CoinGecko

- Datos: precio, volumen, market data agregado, exchanges, derivatives coverage segun plan.
- Free tier: demo/keyless o demo plan; rate limits y creditos mensuales limitados.
- API key: opcional/segun plan.
- Coste: free demo; planes de pago para mas capacidad/frescura.
- Calidad: buena para spot/market data agregado; menos directo para OI/funding/liquidations.
- Decision: no se integra aun porque Binance cubre mejor la primera capa BTC derivatives sin clave.

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
