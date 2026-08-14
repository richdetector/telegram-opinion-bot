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

#### Coin Metrics Community API

- Datos gratuitos usados: contexto BTC de actividad de red disponible en community endpoint, como `TxCnt`, `AdrActCnt` y `HashRate` cuando estan disponibles.
- API: `https://community-api.coinmetrics.io/v4`.
- API key: no necesaria para community endpoints.
- Rate limits: 10 requests cada 6 segundos por IP en community tier.
- Coste: gratuito bajo licencia community para usos permitidos.
- Calidad: fuente robusta para metricas generales de red.
- Limitaciones: no sustituye Glassnode/CryptoQuant para exchange inflows, exchange outflows, exchange reserves, whale-labelled flows, ETF flows ni wallet attribution.
- Decision: integrado como contexto gratuito. Si una metrica no esta en la respuesta, queda `None`; Radar no inventa equivalencias.

### Whale intelligence

- Datos necesarios: wallet labels, exchange/custodian/miner/ETF tags, direction, probable deposit/withdrawal/internal transfer.
- Proveedores habituales: Arkham, Nansen, Chainalysis, Whale Alert.
- Regla: una transferencia aislada no debe producir alerta importante.

### Order book / liquidez

- Datos necesarios: profundidad, clusters de ordenes, cambios de liquidez, liquidation maps.
- Proveedores habituales: exchanges, Bookmap, Hyblock, Coinglass.
- Nota: los mapas de liquidez son estimaciones, no certezas.

### Liquidity + market structure

#### Binance USD-M Futures order book

- Datos: order book real de BTCUSDT perpetual futures (`/fapi/v1/depth`), bid/ask levels, spread, profundidad visible dentro de rangos de precio.
- Free tier/API key: endpoint publico sin API key.
- Rate limits: sujeto a peso por request y limites IP de Binance; exceso devuelve `429` y puede terminar en ban temporal si no se respeta backoff.
- Coste: gratuito.
- Exchange-specific vs aggregated: exchange-specific. Representa Binance USD-M Futures, no todo el mercado global.
- Calidad: buena para libro visible de Binance; no muestra liquidez oculta, ordenes iceberg ni liquidez agregada de otras sedes.
- Decision: implementado como primera capa real de order book. No genera evento `HIGH` por si solo salvo confluencia extrema con otras capas.

#### Coinbase Advanced Trade public/Advanced API

- Datos: product book para BTC-USD, best bid/ask, spread y niveles segun endpoint.
- Free tier/API key: Coinbase Advanced product book documentado requiere autenticacion en endpoint avanzado; hay endpoints publicos de mercado en la familia Advanced/market segun documentacion.
- Coste: sin coste directo de datos para endpoints permitidos, pero requiere configurar API/autenticacion si se usa Advanced.
- Exchange-specific vs aggregated: exchange-specific spot Coinbase.
- Calidad: buena para spot USD regulado, pero no sustituye derivados BTCUSDT.
- Decision: documentado como segunda fuente futura, no activado en esta fase.

#### Kraken public market data

- Datos: order book/pre-trade depth en spot BTC/USD.
- Free tier/API key: endpoints publicos de mercado sin API key; rate limits por IP.
- Exchange-specific vs aggregated: exchange-specific spot Kraken.
- Calidad: buena como contraste spot, menos directa para crowding de derivados.
- Decision: documentado, no activado.

#### CoinGlass

- Datos: futures/spot order book history, large limit orders, liquidation heatmaps/maps, long/short, liquidations, CVD y otros datos agregados.
- Free tier/API key: API V4 requiere API key; varias capas avanzadas dependen de plan.
- Coste: proveedor profesional con planes de pago.
- Exchange-specific vs aggregated: ofrece vistas por exchange y agregadas segun endpoint.
- Calidad: util para mapas agregados, derivados y liquidaciones; los liquidation maps/heatmaps son modelos/estimaciones, no order book real.
- Decision: documentado, no activado para evitar dependencia de pago/API key.

#### Hyblock

- Datos: liquidation heatmap y zonas predictivas de liquidacion por exchange/lookback.
- Free tier/API key: requiere API key u OAuth2 segun documentacion.
- Coste: proveedor profesional; no se activa sin decision explicita.
- Exchange-specific vs aggregated: permite seleccionar venues/modelos.
- Calidad: util para zonas estimadas de riesgo de liquidacion, no equivalente a resting orders reales.
- Decision: documentado, no activado.

#### Real order book vs liquidation maps

- `REAL ORDER BOOK DATA`: niveles visibles de bids/asks en un exchange concreto en un momento concreto. Es observado, pero incompleto: no incluye liquidez oculta ni otros venues.
- `ESTIMATED LIQUIDATION MAPS`: modelos que estiman zonas donde posiciones apalancadas podrian liquidarse. Son utiles para contexto, pero no son ordenes reales y deben tratarse como `INFERRED` o `SPECULATIVE`.

#### Market structure / SMC

- Radar usa estructura tecnica como heuristica: breakouts, failed breakouts, displacement, liquidity sweeps, FVG y break of structure.
- Estas senales no prueban actividad institucional ni manipulacion.
- Una senal SMC aislada nunca debe generar una publicacion final.
- Para elevar confluence necesita coincidir con datos observables: order book, funding, OI, volumen, ETF flows, on-chain o sentimiento extremo.

### Sentimiento

- Datos necesarios: Reddit, Telegram, X/Twitter si hay API legal, titulares, busquedas/tendencias.
- Estado actual: Reddit RSS se ha retirado del feed activo porque devuelve 429 de forma recurrente.
- Integracion robusta recomendada: API oficial o proveedor con rate limits claros.

### Sentiment + positioning + crowding

#### Santiment

- Datos: social volume, social dominance, sentiment/narrative-style crypto metrics, on-chain/dev metrics y series historicas para BTC/ETH.
- API: GraphQL en `https://api.santiment.net`.
- Free tier/API key: API key opcional segun metrica. El plan gratuito ofrece 1,000 API calls/mes, 500/hora y 100/minuto para metricas accesibles; metricas restringidas pueden tener lag o limites historicos.
- Coste: gratuito para una capa ligera; planes de pago para mas capacidad, acceso realtime o metricas restringidas.
- Calidad: proveedor especializado en cripto social/on-chain desde 2014; util como proxy de narrativa/retail attention, no como verdad de mercado.
- Limitaciones: algunas metricas realtime o avanzadas pueden no estar disponibles en free tier. Si la clave falta, la API falla o una metrica no esta accesible, Radar deja `SENTIMENT: UNKNOWN`.
- Decision: primera integracion opcional via `SANTIMENT_API_KEY`. Radar no depende de ella para funcionar.

#### Reddit Data API

- Datos: posts por subreddit, titulo, cuerpo/selftext, permalink, score, comentarios, `created_utc`, flair, autor y `upvote_ratio` cuando Reddit lo entrega.
- Uso en Radar: senal temprana, deteccion de narrativas, retail attention, sentimiento agregado conservador y rumor discovery.
- API: OAuth contra `https://www.reddit.com/api/v1/access_token` y lectura en `https://oauth.reddit.com`.
- Free tier/API key: Reddit documenta 100 QPM por OAuth client id para uso gratuito elegible; trafico sin OAuth puede bloquearse.
- Coste: gratuito para usos elegibles dentro de limites.
- Calidad: buena para narrativa/retail attention; no confirma hechos de mercado.
- Limitaciones: multiples posts Reddit no son confirmacion independiente. Reddit siempre entra como `COMMUNITY`, `rumor_prone=true`, `confidence=Baja` hasta que exista fuente externa fiable.
- Decision: implementado via OAuth. Si faltan credenciales: `REDDIT: NOT_CONFIGURED`. No usar RSS Reddit.

Crear una app Reddit gratis:

1. Ir a `https://www.reddit.com/prefs/apps`.
2. Elegir `are you a developer? create an app`.
3. Crear una app de tipo `script` o `web app` para uso propio/backend.
4. Copiar el client id y client secret.
5. Definir un User-Agent descriptivo, por ejemplo `script:radar-market-intelligence:v1.0 (by /u/tu_usuario)`.
6. Anadir en `.env` local, sin commitear: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`.

#### The Tie

- Datos: sentimiento cuantitativo, actividad social, noticias/narrativas y analytics cripto institucionales.
- API: endpoints REST con header `x-api-key`.
- Free tier/API key: requiere API key; orientado a clientes profesionales/institucionales.
- Coste: proveedor comercial; no se activa sin decision explicita.
- Calidad: alta para sentimiento cripto estructurado, pero dependencia externa de pago.
- Decision: documentado, no activado.

#### Google Trends / search interest

- Datos: interes de busqueda retail y atencion publica.
- API: no hay API oficial estable de Google Trends para esta integracion.
- Alternativas: librerias no oficiales como pytrends, pero dependen de comportamiento web no garantizado.
- Decision: documentado, no implementado para evitar scraping fragil.

La capa implementada combina:

- `RETAIL SENTIMENT`: observado desde una fuente agregada cuando exista.
- `MARKET SENTIMENT`: inferido desde derivados/precio/volatilidad.
- `POSITIONING`: inferido desde OI, funding, liquidaciones y volumen.
- `CROWDING`: solo cuando sentimiento y posicionamiento apuntan juntos.
- `INSTITUTIONAL FLOW PROXY`: inferencia basada en ETF flows y on-chain; no afirma actividad institucional directa.
- `DIVERGENCE`: inferencia cuando retail, derivados, ETF/on-chain o narrativa no estan alineados.

Una senal social aislada no crea evento `HIGH`. Para producir un evento sintetico `MARKET_STATE`, Radar exige confluencia o divergencia clara con derivados/flows/on-chain.

## Capas de certeza

Cada senal debe clasificarse como:

- `OBSERVED`: dato directamente observado.
- `CALCULATED`: calculado sobre datos observados.
- `INFERRED`: inferencia razonable.
- `SPECULATIVE`: posibilidad no confirmada.

Radar no debe mezclar estas capas ni convertirlas en recomendaciones de trading.
