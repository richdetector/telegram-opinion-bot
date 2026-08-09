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

#### Glassnode

- Datos: exchange inflows, exchange outflows, exchange netflows, exchange balances/reserves, whale deposits/withdrawals to/from exchanges, miner flows, LTH/STH and dormancy-style metrics.
- API: REST `https://api.glassnode.com/v1/metrics/...`.
- Free tier/API key: API key required. API access is not automatically included in all plans and may require an add-on.
- Coste: depends on Glassnode plan/API access.
- Wallet/exchange labels: exchange and entity labels maintained by Glassnode; metrics are based on labeled exchange addresses plus data-science/statistical methods.
- Historico: broad historical coverage depending on metric/tier.
- BTC coverage: strong.
- Fiabilidad: high-quality specialized on-chain provider, but recent data can be mutable as labels/statistical attribution improve.
- Decision: implemented as optional provider via `GLASSNODE_API_KEY`. If missing or unavailable, Radar keeps on-chain fields `UNKNOWN` and produces no on-chain signals.

#### Whale Alert

- Datos: large transactions, whale alerts, exchange attribution, transaction owners/labels depending on plan.
- API: WebSocket alerts API and REST enterprise API.
- Free tier/API key: requires developer account/API key and paid subscription/trial.
- Coste: Alerts plan listed at paid monthly pricing; REST/quantitative access is substantially higher.
- Wallet labels: exchange attribution included; depth depends on subscription.
- Historico: limited recent history for API; historical datasets sold separately.
- BTC coverage: yes.
- Fiabilidad: useful for whale transaction alerts, but not enough for aggregate exchange-flow baselines unless on paid API.
- Decision: documented only. Not activated.

#### CryptoQuant

- Datos: BTC exchange inflows/outflows/reserves, miner flows, derivatives/on-chain analytics.
- API: REST endpoints such as BTC exchange flows.
- API key: required.
- Coste: API access requires Professional/Premium plan.
- Wallet/exchange labels: specialized on-chain exchange labeling.
- BTC coverage: strong.
- Decision: documented only. Not activated to avoid paid dependency.

#### Coin Metrics Community API

- Datos: some community asset and exchange metrics without API key; paid tier has broader metrics.
- API: REST `https://community-api.coinmetrics.io/v4`.
- Free tier/API key: community API no key for selected data.
- Coste: community free for non-commercial use; pro data paid.
- Wallet labels: not focused on wallet/entity attribution.
- BTC coverage: strong for general network/market metrics, weaker for labeled whale/exchange-flow intelligence.
- Decision: not used for on-chain exchange labels in this phase.

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
