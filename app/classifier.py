SPANISH_KEYWORDS = [
    "spain",
    "spanish",
    "españa",
    "español",
    "madrid",
    "barcelona",
]

POLITICS = [
    "government",
    "gobierno",
    "minister",
    "president",
    "parliament",
    "parlamento",
    "congress",
    "senate",
    "psoe",
    "pp",
    "vox",
    "sumar",
    "sánchez",
    "feijóo",
]

ECONOMY = [
    "economy",
    "inflation",
    "interest",
    "bce",
    "ecb",
    "bank",
    "bbva",
    "santander",
    "caixabank",
    "ibex",
    "stock",
    "market",
    "tax",
]

HOUSING = [
    "housing",
    "home",
    "house",
    "mortgage",
    "rent",
    "alquiler",
    "vivienda",
    "hipoteca",
]

AI = [
    "ai",
    "artificial intelligence",
    "openai",
    "anthropic",
    "chatgpt",
    "llm",
]

TECH = [
    "apple",
    "google",
    "microsoft",
    "meta",
    "nvidia",
    "cyber",
    "software",
]

GEOPOLITICS = [
    "war",
    "ukraine",
    "russia",
    "china",
    "iran",
    "israel",
    "nato",
    "migration",
    "ceuta",
    "marruecos",
    "morocco",
]

HEALTH = [
    "health",
    "hospital",
    "medicine",
    "covid",
    "cancer",
]


def classify_news(news):

    for item in news:

        text = f"{item.title} {item.summary}".lower()

        score = 0
        category = "General"

        if any(w in text for w in SPANISH_KEYWORDS):
            score += 30

        groups = [
            ("Política", POLITICS, 20),
            ("Economía", ECONOMY, 20),
            ("Vivienda", HOUSING, 20),
            ("IA", AI, 15),
            ("Tecnología", TECH, 12),
            ("Geopolítica", GEOPOLITICS, 18),
            ("Sanidad", HEALTH, 15),
        ]

        best_hits = 0

        for name, words, points in groups:

            hits = sum(word in text for word in words)

            if hits > best_hits:
                best_hits = hits
                category = name

            score += hits * points

        item.category = category

        if item.market_impact <= 0:
            item.score = score

    return news
