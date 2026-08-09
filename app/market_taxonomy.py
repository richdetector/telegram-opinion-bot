DOMAINS = {
    "MACRO",
    "MARKETS",
    "EQUITIES",
    "CRYPTO",
    "GEOPOLITICS",
    "ENERGY",
    "RATES",
    "FX",
    "COMMODITIES",
}

ASSETS = {
    "SP500": ["s&p 500", "sp 500", "sp500", "s&p futures"],
    "NASDAQ": ["nasdaq", "nasdaq 100", "ndx"],
    "DOW": ["dow jones", "dow"],
    "EUROSTOXX": ["euro stoxx", "eurostoxx"],
    "DAX": ["dax"],
    "FTSE": ["ftse"],
    "NIKKEI": ["nikkei"],
    "HANGSENG": ["hang seng", "hangseng"],
    "SHANGHAI": ["shanghai composite", "shanghai"],
    "TREASURIES": ["treasury", "treasuries", "ust", "yield", "yields"],
    "BUNDS": ["bund", "bunds"],
    "EURUSD": ["eur/usd", "eurusd"],
    "USDJPY": ["usd/jpy", "usdjpy", "yen"],
    "USDCNY": ["usd/cny", "usdcny", "yuan", "renminbi"],
    "OIL": ["oil", "crude", "brent", "wti", "opec"],
    "GAS": ["gas", "natural gas", "lng"],
    "GOLD": ["gold"],
    "BTC": ["bitcoin", "btc", "spot bitcoin etf"],
    "ETH": ["ethereum", "ether", "eth", "spot eth etf"],
}

SYSTEMIC_COMPANIES = {
    "NVIDIA": ["nvidia", "nvda"],
    "APPLE": ["apple", "aapl"],
    "MICROSOFT": ["microsoft", "msft"],
    "AMAZON": ["amazon", "amzn", "aws"],
    "META": ["meta", "facebook"],
    "ALPHABET": ["alphabet", "google", "googl"],
    "TESLA": ["tesla", "tsla"],
    "TSMC": ["tsmc", "taiwan semiconductor"],
    "ASML": ["asml"],
    "BROADCOM": ["broadcom", "avgo"],
}

EVENT_KEYWORDS = {
    "CENTRAL_BANK": [
        "fed",
        "fomc",
        "ecb",
        "bce",
        "boj",
        "pboc",
        "central bank",
        "rate decision",
        "interest rates",
        "quantitative tightening",
        "qe",
        "qt",
    ],
    "MACRO_DATA": [
        "cpi",
        "inflation",
        "payrolls",
        "jobs report",
        "employment",
        "unemployment",
        "gdp",
        "pmi",
        "ism",
        "retail sales",
        "ppi",
    ],
    "LIQUIDITY": [
        "liquidity",
        "treasury general account",
        "tga",
        "reverse repo",
        "repo",
        "credit",
        "bank lending",
        "financial conditions",
    ],
    "FISCAL_TRADE": [
        "tariff",
        "tariffs",
        "sanctions",
        "deficit",
        "debt ceiling",
        "treasury issuance",
        "fiscal",
    ],
    "GEOPOLITICAL_MARKET": [
        "strait",
        "taiwan",
        "iran",
        "israel",
        "ukraine",
        "russia",
        "red sea",
        "suez",
        "supply chain",
        "export controls",
    ],
    "CRYPTO_REGULATION": [
        "sec",
        "cftc",
        "etf",
        "spot bitcoin",
        "spot ethereum",
        "stablecoin",
        "custody",
        "reserve",
        "digital asset",
        "crypto regulation",
    ],
    "CRYPTO_MARKET_STRUCTURE": [
        "open interest",
        "funding",
        "liquidation",
        "liquidations",
        "basis",
        "options",
        "put/call",
        "exchange inflow",
        "exchange outflow",
        "whale",
        "on-chain",
        "miner",
    ],
    "SYSTEMIC_COMPANY": [
        "earnings",
        "guidance",
        "capex",
        "supply",
        "demand",
        "antitrust",
        "export restriction",
        "chip",
        "semiconductor",
    ],
}

LOW_VALUE_CRYPTO = [
    "memecoin",
    "meme coin",
    "nft",
    "airdrop",
    "partnership",
    "influencer",
    "price prediction",
    "technical analysis",
    "altcoin",
    "shitcoin",
]

SMALL_PRICE_MOVE_PATTERNS = [
    "sube 0,",
    "cae 0,",
    "rises 0.",
    "falls 0.",
    "up 0.",
    "down 0.",
    "sube 1%",
    "cae 1%",
    "rises 1%",
    "falls 1%",
    "sube 2%",
    "cae 2%",
    "rises 2%",
    "falls 2%",
]


def text_blob(item):
    return f"{item.title} {item.summary} {item.content}".lower()


def detect_assets(text):
    assets = []
    for asset, keywords in ASSETS.items():
        if any(keyword in text for keyword in keywords):
            assets.append(asset)

    for company, keywords in SYSTEMIC_COMPANIES.items():
        if any(keyword in text for keyword in keywords):
            assets.append(company)

    return assets


def detect_event_type(text):
    best_event = "UNKNOWN"
    best_hits = 0

    for event_type, keywords in EVENT_KEYWORDS.items():
        hits = sum(keyword in text for keyword in keywords)
        if hits > best_hits:
            best_event = event_type
            best_hits = hits

    return best_event


def asset_class_for_assets(assets, event_type):
    if any(asset in {"BTC", "ETH"} for asset in assets):
        return "CRYPTO"
    if any(asset in {"TREASURIES", "BUNDS"} for asset in assets):
        return "RATES"
    if any(asset in {"EURUSD", "USDJPY", "USDCNY"} for asset in assets):
        return "FX"
    if any(asset in {"OIL", "GAS", "GOLD"} for asset in assets):
        return "COMMODITIES"
    if any(asset in SYSTEMIC_COMPANIES for asset in assets):
        return "EQUITIES"
    if event_type in {"CENTRAL_BANK", "MACRO_DATA", "LIQUIDITY", "FISCAL_TRADE"}:
        return "MACRO"
    if event_type == "GEOPOLITICAL_MARKET":
        return "GEOPOLITICS"
    return "UNKNOWN"
