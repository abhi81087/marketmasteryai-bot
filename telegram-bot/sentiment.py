import yfinance as yf

BULLISH_WORDS = {
    "surge", "surges", "surging", "rally", "rallies", "rallying", "soar", "soars", "soaring",
    "beat", "beats", "beating", "record", "records", "growth", "grows", "growing",
    "profit", "profits", "upgrade", "upgrades", "upgraded", "buy", "bullish",
    "rise", "rises", "rising", "gain", "gains", "strong", "strength", "outperform",
    "positive", "boost", "boosts", "boosted", "jump", "jumps", "jumped",
    "high", "highs", "expand", "expansion", "optimistic", "opportunity",
    "breakthrough", "win", "wins", "winning", "recover", "recovery", "recovers",
    "top", "better", "above", "exceed", "exceeds", "exceeded", "upbeat",
    "increase", "increases", "increased", "accelerate", "acceleration",
}

BEARISH_WORDS = {
    "fall", "falls", "falling", "drop", "drops", "dropping", "miss", "misses", "missed",
    "loss", "losses", "decline", "declines", "declining", "cut", "cuts", "cutting",
    "downgrade", "downgrades", "downgraded", "sell", "bearish", "crash", "crashes",
    "weak", "weakness", "concern", "concerns", "risk", "risks", "lawsuit", "sued",
    "investigation", "probe", "fine", "fined", "penalty", "penalties",
    "drop", "slump", "slumps", "slumping", "tumble", "tumbles", "tumbling",
    "low", "lows", "below", "miss", "disappoint", "disappoints", "disappointing",
    "decrease", "decreases", "decreased", "decelerate", "deceleration",
    "warning", "warns", "warned", "layoff", "layoffs", "restructure", "restructuring",
    "debt", "deficit", "shortage", "supply", "delay", "delays", "delayed",
    "recall", "recalls", "suspended", "halt", "halts", "ban", "banned",
}


def score_headline(title: str) -> int:
    words = title.lower().split()
    score = 0
    for w in words:
        clean = w.strip(".,!?;:\"'()")
        if clean in BULLISH_WORDS:
            score += 1
        elif clean in BEARISH_WORDS:
            score -= 1
    return score


def fetch_sentiment(ticker: str) -> dict:
    stock = yf.Ticker(ticker)
    news = stock.news

    if not news:
        return {
            "ticker": ticker,
            "total": 0,
            "bullish": 0,
            "bearish": 0,
            "neutral": 0,
            "overall": "No recent news found",
            "sentiment": "NEUTRAL",
            "headlines": [],
        }

    scored = []
    for item in news[:15]:
        content = item.get("content", {})
        title = (
            content.get("title")
            or item.get("title")
            or ""
        )
        link = ""
        click_through = content.get("clickThroughUrl") or {}
        if isinstance(click_through, dict):
            link = click_through.get("url", "")
        if not link:
            link = content.get("canonicalUrl", {}).get("url", "") if isinstance(content.get("canonicalUrl"), dict) else ""

        if not title:
            continue

        score = score_headline(title)
        scored.append({"title": title, "score": score, "link": link})

    bullish = sum(1 for s in scored if s["score"] > 0)
    bearish = sum(1 for s in scored if s["score"] < 0)
    neutral = sum(1 for s in scored if s["score"] == 0)
    total_score = sum(s["score"] for s in scored)

    if total_score >= 3 or (bullish >= 2 and bullish > bearish * 2):
        overall = "BULLISH"
    elif total_score <= -3 or (bearish >= 2 and bearish > bullish * 2):
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"

    scored.sort(key=lambda x: abs(x["score"]), reverse=True)

    return {
        "ticker": ticker,
        "total": len(scored),
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "overall": overall,
        "total_score": total_score,
        "headlines": scored[:8],
    }
