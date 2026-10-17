"""Local decision adapter. Gemma via Ollama picks the label. Cash and units stay computed here."""
import json
import os
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.environ.get("MERCURE_MODEL", "gemma3:4b")
TIMEOUT = 120
SOURCE = "Gemma3 (Local Decision Model)"
MULT = {"HIGH_SURGE": 2.2, "MODERATE_GROWTH": 1.35, "STABLE": 1.0, "SLUMP": 0.6}
MARKDOWNS = ("10", "15", "20")


def _context(sku):
    cat = sku.get("cat") or ""
    if cat == "Jackets":
        return "Seasonal outerwear. A heavy winter jacket in tropical Bengaluru during October is a climate mismatch."
    if cat in ("Shirts", "Pants", "Shoes"):
        return "Staple category. Benchmark shelf life is longer than one festival season."
    return "Fashion category. Benchmark shelf life is a single season."


def _unit(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _regime(value):
    key = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "HIGH": "HIGH_SURGE",
        "SURGE": "HIGH_SURGE",
        "MODERATE": "MODERATE_GROWTH",
        "GROWTH": "MODERATE_GROWTH",
        "LOW": "SLUMP",
        "DECLINE": "SLUMP",
    }
    if key in MULT:
        return key
    return aliases.get(key)


def _markdown(value):
    text = str(value or "").replace("%", "").strip()
    if text in ("0.1", "0.10"):
        return "10"
    if text in ("0.15",):
        return "15"
    if text in ("0.2", "0.20"):
        return "20"
    if text in MARKDOWNS:
        return text
    return None


def _parse_items(text):
    raw = json.loads(text)
    items = raw.get("items") if isinstance(raw, dict) else raw
    if isinstance(raw, dict) and not items:
        items = [raw]
    if not isinstance(items, list):
        raise RuntimeError("model-bad-json")
    return items


def ask(skus):
    lines = []
    for sku in skus:
        lines.append(
            "%s | %s | %s | age %s days | velocity %s/day | cover %s days | capital %s | events %s | %s"
            % (
                sku.get("id"),
                sku.get("name") or sku.get("id"),
                sku.get("cat"),
                sku.get("age"),
                sku.get("baseline"),
                sku.get("days"),
                sku.get("capital"),
                ", ".join(sku.get("events") or []) or "none",
                _context(sku),
            )
        )
    prompt = (
        "You decide inventory for a Bengaluru apparel shop. "
        "Return JSON {\"items\":[...]} with one object per product, same order. "
        "Fields: id, regime, regime_confidence, dead, markdown, markdown_confidence. "
        "regime is exactly HIGH_SURGE, MODERATE_GROWTH, STABLE, or SLUMP, judged against the given daily velocity and events. "
        "dead is the probability this stock will not sell, from 0 to 1. "
        "markdown is exactly 10, 15, or 20. "
        "confidences are from 0 to 1. Do not invent rupees.\n"
        + "\n".join(lines)
    )
    body = json.dumps({
        "model": MODEL,
        "stream": False,
        "format": "json",
        "keep_alive": "10m",
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0, "num_predict": 80 * max(1, len(skus))},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            data = json.loads(res.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("model-unavailable") from exc
    try:
        return _parse_items((data.get("message") or {}).get("content") or "")
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise RuntimeError("model-bad-json") from exc


def _cash(units, vel, price, rate):
    moved = min(float(units or 0), float(vel or 0) * (1 + rate * 3) * 30)
    return round(moved * float(price or 0) * (1 - rate)), moved


def _rows(sku, item):
    regime = _regime(item.get("regime"))
    mark = _markdown(item.get("markdown"))
    dead = _unit(item.get("dead"))
    regime_conf = _unit(item.get("regime_confidence"))
    mark_conf = _unit(item.get("markdown_confidence"))
    if not regime or not mark or dead is None or regime_conf is None or mark_conf is None:
        raise RuntimeError("model-bad-row")
    baseline = float(sku.get("baseline") or 0)
    rate = int(mark) / 100
    price = sku.get("price") or 0
    cash, moved = _cash(sku.get("units"), baseline, price, rate)
    vel = float(baseline or 0.05) or 0.05
    return (
        {
            "id": sku.get("id"),
            "source": SOURCE,
            "regime": regime,
            "confidence": round(regime_conf * 100, 1),
            "baseline": round(baseline, 2),
            "rate": round(baseline * MULT[regime], 2),
            "review": regime_conf < 0.8,
        },
        {
            "id": sku.get("id"),
            "source": SOURCE,
            "probability": round(dead * 100, 1),
            "markdown": rate,
            "confidence": round(mark_conf * 100, 1),
            "cash": cash,
            "days": int(round(moved / max(vel, 0.05))) if moved else 0,
            "review": mark_conf < 0.8 or min(dead, 1 - dead) > 0.2,
            "context": _context(sku),
        },
    )


def decide(body):
    skus = body.get("skus") if isinstance(body, dict) and body.get("skus") else [body]
    items = ask(skus)
    by_id = {}
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item.get("id"))] = item
    forecasts = []
    dead = []
    for index, sku in enumerate(skus):
        item = by_id.get(str(sku.get("id"))) or (items[index] if index < len(items) else None)
        if not isinstance(item, dict):
            continue
        try:
            forecast_row, dead_row = _rows(sku, item)
        except RuntimeError:
            continue
        forecasts.append(forecast_row)
        dead.append(dead_row)
    if not forecasts:
        raise RuntimeError("model-bad")
    return {"forecasts": forecasts, "dead": dead}


def forecast(sku):
    row = next((item for item in decide(sku)["forecasts"] if item["id"] == sku.get("id")), None)
    if not row:
        raise RuntimeError("model-bad-forecast")
    return row


def dead_stock(sku):
    row = next((item for item in decide(sku)["dead"] if item["id"] == sku.get("id")), None)
    if not row:
        raise RuntimeError("model-bad-dead")
    return row


if __name__ == "__main__":
    sample = _parse_items(
        '{"items":[{"id":"JKT-409","regime":"SLUMP","regime_confidence":0.91,'
        '"dead":0.96,"markdown":20,"markdown_confidence":0.88}]}'
    )
    forecast_row, dead_row = _rows(
        {"id": "JKT-409", "cat": "Jackets", "units": 47, "baseline": 0.34, "price": 1499},
        sample[0],
    )
    assert forecast_row["regime"] == "SLUMP"
    assert forecast_row["rate"] == round(0.34 * 0.6, 2)
    assert dead_row["markdown"] == 0.2 and dead_row["cash"] > 0
    assert dead_row["review"] is False
    print("model_service ok", dead_row["cash"])
