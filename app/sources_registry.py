SOURCE_TYPES = {
    "PRIMARY": 95,
    "HIGH_RELIABILITY": 85,
    "FAST": 55,
    "COMMUNITY": 30,
    "BACKGROUND": 45,
}

SOURCE_REGISTRY = {
    "MARKET_STATE": {"type": "PRIMARY", "reliability": 70, "speed": 80},
    "Federal Reserve - Monetary Policy": {"type": "PRIMARY", "reliability": 98, "speed": 80},
    "Federal Reserve - All Press Releases": {"type": "PRIMARY", "reliability": 98, "speed": 75},
    "Federal Reserve - Balance Sheet": {"type": "PRIMARY", "reliability": 98, "speed": 65},
    "BLS - Employment Situation": {"type": "PRIMARY", "reliability": 98, "speed": 80},
    "BLS - CPI": {"type": "PRIMARY", "reliability": 98, "speed": 80},
    "BLS - PPI": {"type": "PRIMARY", "reliability": 96, "speed": 75},
    "SEC - Press Releases": {"type": "PRIMARY", "reliability": 98, "speed": 80},
    "TreasuryDirect - Auction Announcements": {"type": "PRIMARY", "reliability": 95, "speed": 70},
    "TreasuryDirect - Auction Results": {"type": "PRIMARY", "reliability": 95, "speed": 70},
    "Banco Central Europeo": {"type": "PRIMARY", "reliability": 95, "speed": 70},
    "Banco de España": {"type": "PRIMARY", "reliability": 90, "speed": 50},
    "CNMV": {"type": "PRIMARY", "reliability": 90, "speed": 50},
    "Comisión Europea": {"type": "PRIMARY", "reliability": 90, "speed": 55},
    "MarketWatch": {"type": "HIGH_RELIABILITY", "reliability": 75, "speed": 70},
    "CNBC": {"type": "HIGH_RELIABILITY", "reliability": 78, "speed": 80},
    "FinancialTimes": {"type": "HIGH_RELIABILITY", "reliability": 88, "speed": 75},
    "Bloomberg": {"type": "HIGH_RELIABILITY", "reliability": 90, "speed": 85},
    "CoinDesk": {"type": "HIGH_RELIABILITY", "reliability": 72, "speed": 78},
    "Cointelegraph": {"type": "BACKGROUND", "reliability": 55, "speed": 75},
    "NVIDIA Blog": {"type": "PRIMARY", "reliability": 82, "speed": 65},
    "Apple Newsroom": {"type": "PRIMARY", "reliability": 82, "speed": 60},
    "Microsoft Blog": {"type": "PRIMARY", "reliability": 82, "speed": 60},
    "ClashReport": {"type": "FAST", "reliability": 55, "speed": 90, "rumor_prone": True},
    "OSINTdefender": {"type": "FAST", "reliability": 55, "speed": 90, "rumor_prone": True},
    "Faytuks": {"type": "FAST", "reliability": 60, "speed": 90, "rumor_prone": True},
    "OpenAI": {"type": "PRIMARY", "reliability": 80, "speed": 70},
    "AnthropicAI": {"type": "PRIMARY", "reliability": 80, "speed": 70},
    "NVIDIAAI": {"type": "FAST", "reliability": 35, "speed": 70, "rumor_prone": True},
    "NoticiasTradingCrypto": {"type": "FAST", "reliability": 35, "speed": 85, "rumor_prone": True},
    "ultimominutoOTC": {"type": "FAST", "reliability": 35, "speed": 85, "rumor_prone": True},
    "binancekillers": {"type": "FAST", "reliability": 30, "speed": 85, "rumor_prone": True},
    "Truth Social @realDonaldTrump": {
        "type": "FAST",
        "reliability": 70,
        "speed": 95,
        "rumor_prone": True,
        "market_sensitive": True,
    },
}

BACKGROUND_SOURCES = {
    "El País",
    "El Mundo",
    "ABC",
    "La Vanguardia",
    "20 Minutos",
    "El Confidencial",
    "El Español",
    "Europa Press",
    "RTVE",
    "El Independiente",
    "Vozpópuli",
    "BBC World",
    "The Guardian World",
    "France24",
    "Deutsche Welle",
    "Al Jazeera",
    "Euronews",
    "UN News",
}


def source_metadata(source):
    if source in SOURCE_REGISTRY:
        return SOURCE_REGISTRY[source].copy()

    if source.startswith("r/"):
        return {
            "type": "COMMUNITY",
            "reliability": 25,
            "speed": 65,
            "rumor_prone": True,
        }

    if source in BACKGROUND_SOURCES:
        return {
            "type": "BACKGROUND",
            "reliability": 50,
            "speed": 55,
            "rumor_prone": False,
        }

    return {
        "type": "BACKGROUND",
        "reliability": 45,
        "speed": 45,
        "rumor_prone": False,
    }


def apply_source_metadata(item):
    meta = source_metadata(item.source)

    item.source_type = meta.get("type", "BACKGROUND")
    item.source_reliability = meta.get("reliability", 40)
    item.source_speed = meta.get("speed", 40)

    if meta.get("rumor_prone"):
        item.is_rumor = True

    if item.source_type == "PRIMARY":
        item.is_confirmed = True
        item.verification_status = "CONFIRMED"
        item.confidence = "Alta"
        item.primary_source = item.source

    return item
