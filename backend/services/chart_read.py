"""Chart read: you drop a screenshot of your TradingView chart into the app and get it back marked up.

Who does what
  Claude (Anthropic API, vision) READS the picture: the symbol and timeframe, the last price, two price labels on the price
  scale and their heights (so a price can be turned into a height on the image), where the last candle sits and how far apart
  candles are, which of the app's levels are on the chart, and what the candles around each level are doing.
  Q DATA DECIDES the calls (respect / chop / disrespect, services/behavior.py) and the projected path, exactly as on the Level map
  tab, from today's options data. Claude may flag a level where the chart already disagrees (for example a level that was already
  broken), and that note is shown next to the call; it does not replace the call.

The API key lives only in your .env file (ANTHROPIC_API_KEY) and is sent only to api.anthropic.com. Each read is one paid request.
"""
from __future__ import annotations
import base64
import json
import re

import httpx

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_IMAGE_BYTES = 4_500_000

TOOL = {
    "name": "chart_read",
    "description": "Report what the trading chart screenshot shows, in numbers that let the app draw on it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Symbol shown on the chart, e.g. NQ1!, MNQZ2026, ES1!. Empty if not visible."},
            "timeframe": {"type": "string", "description": "Candle timeframe shown, e.g. 1m, 5m. Empty if not visible."},
            "last_price": {"type": "number", "description": "The current / last price shown (price label on the scale or the latest close)."},
            "axis": {"type": "object", "description": "Two price labels read off the right-hand price scale, far apart, and the vertical centre of each label as a fraction of the image height (0 = top, 1 = bottom).",
                     "properties": {"p1": {"type": "number"}, "y1": {"type": "number"}, "p2": {"type": "number"}, "y2": {"type": "number"}},
                     "required": ["p1", "y1", "p2", "y2"]},
            "last_candle_x": {"type": "number", "description": "Horizontal centre of the most recent candle as a fraction of the image width (0 = left, 1 = right)."},
            "candle_spacing": {"type": "number", "description": "Distance between neighbouring candle centres as a fraction of the image width."},
            "plot_right_x": {"type": "number", "description": "Right edge of the plotting area (where the price scale starts) as a fraction of the image width."},
            "structure": {"type": "string", "description": "Two or three plain sentences on what price is doing on this chart: trend or range, the last swing high and low, how the latest candles behave."},
            "levels_seen": {"type": "array", "description": "For each app level that is within the visible price range: what the candles have done there so far on this chart.",
                            "items": {"type": "object", "properties": {
                                "price": {"type": "number", "description": "The app level's price (as given to you)."},
                                "chart_behavior": {"type": "string", "enum": ["not_reached", "respected", "broken", "chopping", "unclear"]},
                                "note": {"type": "string", "description": "One short sentence, e.g. 'two wicks above it at 10:05 and 10:20, closed back under'."}},
                                "required": ["price", "chart_behavior"]}},
            "readable": {"type": "boolean", "description": "False if the price scale or candles cannot be read reliably."},
            "problem": {"type": "string", "description": "If not readable, what is wrong (cropped scale, no candles, not a price chart...)."},
        },
        "required": ["last_price", "axis", "last_candle_x", "candle_spacing", "plot_right_x", "structure", "levels_seen", "readable"],
    },
}


def parse_data_url(data_url: str):
    """'data:image/png;base64,....' -> (media_type, base64 text). Raises ValueError for anything else."""
    m = re.match(r"^data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\s]+)$", data_url or "")
    if not m:
        raise ValueError("Send the screenshot as a PNG, JPEG, WEBP or GIF image.")
    b64 = re.sub(r"\s", "", m.group(2))
    if len(b64) * 3 // 4 > MAX_IMAGE_BYTES:
        raise ValueError("The image is too large. Crop it to the chart or send a smaller screenshot.")
    base64.b64decode(b64[:64] + "=" * (-len(b64[:64]) % 4))       # quick sanity check
    return m.group(1), b64


def build_prompt(levels, regime, unit, note=""):
    rows = "\n".join(f"- {l['price']:.2f}  {l['label']}  (app call: {l['call']})" for l in levels) or "- none near price"
    return (f"This is a screenshot of a trading chart. The trader's app (Q DATA) has these options-based levels for today, in {unit} points:\n{rows}\n\n"
            f"Today's gamma regime from the app: {regime}.\n"
            + (f"The trader adds: {note}\n" if note else "")
            + "Read the chart carefully and call the chart_read tool. Read prices from the right-hand price scale labels exactly as printed; pick two labels far apart "
              "for the axis. Positions are fractions of the full image (0 to 1). For levels_seen, include only app levels whose price is inside the visible price range, "
              "and describe only what the candles on this chart actually did there. Do not predict; the app makes the calls. If the scale or candles cannot be read, "
              "set readable to false and say why.")


def read_chart(api_key, media_type, b64, levels, regime, unit, note="", model=DEFAULT_MODEL, client=None):
    """One request to the Anthropic Messages API. Returns the tool input as a dict. Raises RuntimeError with a plain message on failure."""
    body = {"model": model, "max_tokens": 1500, "tools": [TOOL], "tool_choice": {"type": "tool", "name": "chart_read"},
            "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                                                      {"type": "text", "text": build_prompt(levels, regime, unit, note)}]}]}
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    own = client is None
    client = client or httpx.Client(timeout=90.0)
    try:
        r = client.post(API_URL, headers=headers, content=json.dumps(body))
    except httpx.HTTPError as e:
        raise RuntimeError(f"Could not reach the Anthropic API ({type(e).__name__}). Check the internet connection.") from None
    finally:
        if own:
            client.close()
    if r.status_code == 401:
        raise RuntimeError("The Anthropic API key was not accepted. Check ANTHROPIC_API_KEY.")
    if r.status_code == 429:
        raise RuntimeError("The Anthropic API is rate-limiting this key. Wait a minute and try again.")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = r.text[:200]
        raise RuntimeError(f"The Anthropic API returned an error ({r.status_code}): {msg[:300]}")
    for block in r.json().get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "chart_read":
            return block.get("input") or {}
    raise RuntimeError("The model did not return a chart reading. Try again or send a clearer screenshot.")


def check_reading(rd):
    """Plain sanity checks on the numbers the model read. Returns a list of problems (empty = usable)."""
    out = []
    ax = rd.get("axis") or {}
    try:
        p1, y1, p2, y2 = float(ax["p1"]), float(ax["y1"]), float(ax["p2"]), float(ax["y2"])
        if p1 == p2 or abs(y1 - y2) < 0.05:
            out.append("The two price-scale labels are too close together to scale the chart.")
        elif (p1 - p2) * (y2 - y1) <= 0:
            out.append("The price scale reads upside down (higher prices should sit higher on the image).")
    except (KeyError, TypeError, ValueError):
        out.append("The price scale could not be read.")
    for k in ("last_candle_x", "plot_right_x"):
        v = rd.get(k)
        if not isinstance(v, (int, float)) or not 0 <= v <= 1:
            out.append(f"{k} is missing or outside the image.")
    sp = rd.get("candle_spacing")
    if not isinstance(sp, (int, float)) or not 0 < sp < 0.2:
        out.append("The candle spacing could not be read.")
    if rd.get("readable") is False:
        out.append(rd.get("problem") or "The model could not read the chart.")
    return out
