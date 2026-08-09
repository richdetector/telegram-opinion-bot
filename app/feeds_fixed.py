RSS_FEEDS = [
    # ==========================================================
    # PRIMARY - MACRO / RATES / REGULATION
    # ==========================================================
    {
        "name": "Federal Reserve - Monetary Policy",
        "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "category": "macro",
        "weight": 30,
    },
    {
        "name": "Federal Reserve - All Press Releases",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "macro",
        "weight": 28,
    },
    {
        "name": "Federal Reserve - Balance Sheet",
        "url": "https://www.federalreserve.gov/feeds/h41.xml",
        "category": "liquidity",
        "weight": 26,
    },
    {
        "name": "BLS - Employment Situation",
        "url": "https://www.bls.gov/feed/empsit.rss",
        "category": "macro",
        "weight": 30,
    },
    {
        "name": "BLS - CPI",
        "url": "https://www.bls.gov/feed/cpi.rss",
        "category": "macro",
        "weight": 30,
    },
    {
        "name": "BLS - PPI",
        "url": "https://www.bls.gov/feed/ppi.rss",
        "category": "macro",
        "weight": 26,
    },
    {
        "name": "SEC - Press Releases",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "category": "regulation",
        "weight": 30,
    },
    {
        "name": "TreasuryDirect - Auction Announcements",
        "url": "https://www.treasurydirect.gov/TA_WS/securities/announced/rss",
        "category": "rates",
        "weight": 26,
    },
    {
        "name": "TreasuryDirect - Auction Results",
        "url": "https://www.treasurydirect.gov/TA_WS/securities/auctioned/rss",
        "category": "rates",
        "weight": 24,
    },
    {
        "name": "Banco Central Europeo",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "category": "macro",
        "weight": 28,
    },
    {
        "name": "Comisión Europea",
        "url": "https://ec.europa.eu/commission/presscorner/api/rss",
        "category": "regulation",
        "weight": 22,
    },

    # ==========================================================
    # HIGH RELIABILITY - MARKETS / MACRO
    # ==========================================================
    {
        "name": "CNBC",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "category": "markets",
        "weight": 20,
    },
    {
        "name": "MarketWatch",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "category": "markets",
        "weight": 18,
    },
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
        "category": "world",
        "weight": 14,
    },
    {
        "name": "Al Jazeera",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "category": "geopolitics",
        "weight": 14,
    },
    {
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "category": "world",
        "weight": 12,
    },

    # ==========================================================
    # SYSTEMIC COMPANIES / TECHNOLOGY
    # ==========================================================
    {
        "name": "NVIDIA Blog",
        "url": "https://blogs.nvidia.com/feed/",
        "category": "systemic_company",
        "weight": 20,
    },
    {
        "name": "Apple Newsroom",
        "url": "https://www.apple.com/newsroom/rss-feed.rss",
        "category": "systemic_company",
        "weight": 18,
    },
    {
        "name": "Microsoft Blog",
        "url": "https://blogs.microsoft.com/feed/",
        "category": "systemic_company",
        "weight": 18,
    },
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "category": "technology",
        "weight": 12,
    },

    # ==========================================================
    # CRYPTO - INSTITUTIONAL / REGULATORY / COMMUNITY SIGNALS
    # ==========================================================
    {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "category": "crypto",
        "weight": 16,
    },
    {
        "name": "Cointelegraph",
        "url": "https://cointelegraph.com/rss",
        "category": "crypto",
        "weight": 12,
    },
]
