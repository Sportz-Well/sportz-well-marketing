"""Researcher agent — first agent in the pipeline.

Searches the web for recent, relevant content on a given topic, validates URLs,
scores each result for brand fit, and saves to research_items. Every API call
is logged to both data/api_log.csv and the api_log database table.

Prompt-3.5 additions:
  - URL validation (concurrent HEAD/GET, 5 workers)
  - Configurable geography mix
  - Quality threshold (no padding with weak results)
  - Source domain bias (soft allowlist + downrank list)

Public API
----------
research_topic(topic, product_id, max_results, min_relevance, geography) -> dict
GEOGRAPHY_OPTIONS  — dict mapping display label → prompt instruction (for UI)
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.anthropic_client import ask_with_web_search, DEFAULT_MODEL
from services.brand_context import build_brand_context_prompt
from services.database import get_connection
from services.source_preferences import format_source_preferences
from services.url_validator import validate_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_LOG_PATH = PROJECT_ROOT / "data" / "api_log.csv"

# Pricing constants for claude-sonnet-4-6 (USD per token)
_INPUT_COST_PER_TOKEN  = 3.00  / 1_000_000
_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000
_SEARCH_COST_PER_USE   = 0.01

# Geography options — display label → prompt instruction injected into system prompt.
GEOGRAPHY_OPTIONS: dict[str, str] = {
    "Indian-heavy (3:2)": (
        "Aim for roughly 60% Indian sources and 40% international. "
        "If quality Indian sources are scarce on this topic, use higher-quality "
        "international sources — quality always beats geography."
    ),
    "Balanced (1:1)": (
        "Aim for roughly equal Indian and international sources. "
        "Choose the best-quality mix."
    ),
    "Global-heavy (2:3)": (
        "Aim for roughly 40% Indian and 60% international. "
        "Prefer international sources when quality is comparable."
    ),
    "India-only": (
        "Only include sources from Indian publications, organisations, or researchers. "
        "If fewer than requested items meet the threshold from Indian sources, "
        "return fewer items — do not substitute non-Indian sources."
    ),
    "No preference": (
        "Source geography is not a factor. Choose the highest-quality, "
        "most relevant sources regardless of country."
    ),
}

_DEFAULT_GEOGRAPHY = "Indian-heavy (3:2)"
_DEFAULT_MIN_RELEVANCE = 7


# ─── Public entry point ───────────────────────────────────────────────────────

def research_topic(
    topic: str,
    product_id: int,
    max_results: int = 8,
    min_relevance: int = _DEFAULT_MIN_RELEVANCE,
    geography: str = _DEFAULT_GEOGRAPHY,
) -> dict[str, Any]:
    """Search the web for *topic*, validate URLs, score for brand fit, save to DB.

    Returns:
        {
            "topic":                   str,
            "items_saved":             int,
            "total_cost_estimate_usd": float,
            "items":                   list[dict],
            "error":                   str | None,
            "requested_count":         int,
            "met_threshold_count":     int,
            "rejected_count":          int,
            "rejection_summary":       str,
        }
    """
    geo_instruction = GEOGRAPHY_OPTIONS.get(geography, GEOGRAPHY_OPTIONS[_DEFAULT_GEOGRAPHY])
    brand_ctx       = build_brand_context_prompt(product_id)
    source_prefs    = format_source_preferences()
    system_prompt   = _build_system_prompt(brand_ctx, max_results, min_relevance,
                                           geo_instruction, source_prefs)
    user_prompt     = f"Research this topic and return JSON results: {topic}"

    api_result = ask_with_web_search(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=DEFAULT_MODEL,
        max_tokens=4096,
    )

    cost = _estimate_cost(
        api_result["input_tokens"],
        api_result["output_tokens"],
        api_result["web_searches"],
    )

    if api_result["error"]:
        _log_api_call(topic, api_result["input_tokens"], api_result["output_tokens"],
                      api_result["web_searches"], cost, f"ERROR: {api_result['error'][:200]}")
        return _error_result(topic, cost, api_result["error"], max_results)

    parse_result = _parse_research_json(api_result["text"])
    raw_items    = parse_result["raw_items"]

    if not raw_items:
        _log_api_call(topic, api_result["input_tokens"], api_result["output_tokens"],
                      api_result["web_searches"], cost, "WARNING: response not parseable as JSON")
        return _error_result(
            topic, cost,
            "The model returned a response that could not be parsed as JSON. "
            "Raw response (first 500 chars): " + api_result["text"][:500],
            max_results,
        )

    # Client-side structure check and threshold filter (safety net)
    struct_valid = _validate_structure(raw_items)
    passing      = [i for i in struct_valid if i["relevance_score"] >= min_relevance]
    extra_reject = len(struct_valid) - len(passing)

    # URL validation — concurrent, max 5 workers
    passing = _validate_urls_batch(passing)

    # Trim to max_results
    passing = passing[:max_results]

    saved = _save_items(passing, product_id, topic)

    total_rejected  = parse_result["model_rejected_count"] + extra_reject
    rejection_summary = parse_result["rejection_summary"]
    if extra_reject > 0:
        rejection_summary = (
            rejection_summary
            + f" (plus {extra_reject} additional item(s) removed client-side below threshold {min_relevance})"
        ).strip()

    _log_api_call(
        topic, api_result["input_tokens"], api_result["output_tokens"],
        api_result["web_searches"], cost,
        f"Saved {saved}/{max_results} requested, {total_rejected} rejected, threshold={min_relevance}",
    )

    return {
        "topic":                   topic,
        "items_saved":             saved,
        "total_cost_estimate_usd": cost,
        "items":                   passing,
        "error":                   None,
        "requested_count":         max_results,
        "met_threshold_count":     saved,
        "rejected_count":          total_rejected,
        "rejection_summary":       rejection_summary,
    }


def _error_result(topic: str, cost: float, error: str, requested: int) -> dict:
    return {
        "topic": topic, "items_saved": 0, "total_cost_estimate_usd": cost,
        "items": [], "error": error, "requested_count": requested,
        "met_threshold_count": 0, "rejected_count": 0, "rejection_summary": "",
    }


# ─── Prompt construction ──────────────────────────────────────────────────────

def _build_system_prompt(
    brand_ctx: str,
    max_results: int,
    min_relevance: int,
    geography_instruction: str,
    source_prefs: str,
) -> str:
    return f"""You are the Researcher agent for a social media content pipeline.

{brand_ctx}

## Your Task

Use web search to find up to {max_results} recent, high-quality articles, research papers, or reports relevant to the given topic. After searching, return ONLY a JSON object (no preamble, no markdown fences) with the structure described below.

## Geography Preference

{geography_instruction}
Regardless of geography preference: if a non-preferred source is substantially higher quality (more authoritative, more recent, better-evidenced) than a preferred-geography alternative, choose the higher-quality source and note this in relevance_reason.

## Quality Threshold

**Only include items with relevance_score ≥ {min_relevance}.** Do not pad the list with weaker results to reach {max_results} items. If only 3 items meet the threshold, return 3.
Count how many items you found but rejected for being below the threshold, and include that count in the JSON.

{source_prefs}

## Output Format

Return a JSON object with exactly this structure:

{{
  "items": [
    {{
      "title": "article or page title",
      "source_url": "full URL",
      "source_published_date": "YYYY-MM-DD or null",
      "summary": "3-5 sentences summarising the key points",
      "relevance_score": <integer {min_relevance}–10>,
      "relevance_reason": "one sentence explaining the score, mentioning any source-preference adjustments",
      "source_geography": "India" | "UK" | "Australia" | "USA" | "Global" | "Unknown"
    }}
  ],
  "rejected_count": <integer — items found but below threshold {min_relevance}>,
  "rejection_summary": "brief description of what you rejected and why (one or two sentences)"
}}

## Relevance Scoring

Score each item against the Brand Context above:
- **9–10**: Perfect fit — directly aligned with owned topics (grassroots cricket India, academy/school context, coach–parent communication, mental toughness as trainable skill, AI as coach-assistant, Mumbai/Maharashtra sports)
- **7–8**: Strong fit — useful for brand content, good source quality, Indian sports context
- **5–6**: Moderate fit — tangentially related, needs adaptation (below threshold unless threshold is ≤ 5)
- **3–4**: Weak fit — generic, limited brand relevance
- **1–2**: Off-brand

**Prefer**: peer-reviewed sports science, coach/academy contexts, Indian sources, Mumbai/Maharashtra angles
**Avoid**: national team politics, supplement advice, generic Western fitness, celebrity drama, topics in the brand's "Topics We Avoid" list

## Rules

- Return ONLY the JSON object — no other text before or after
- Do not fabricate URLs or dates — only include what you actually found
- Each item must have all 7 fields; use null for missing optional values"""


# ─── Response parsing ─────────────────────────────────────────────────────────

def _parse_research_json(text: str) -> dict[str, Any]:
    """Extract items and rejection metadata from the model's JSON response.

    Handles two formats:
      - Object: {"items": [...], "rejected_count": N, "rejection_summary": "..."}
      - Array:  [...] (backward compat)

    Returns {"raw_items": list, "model_rejected_count": int, "rejection_summary": str}
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    candidates = [text]
    # Also try the first {...} or [...] span in case of leading/trailing prose
    obj_match = re.search(r"\{[\s\S]*\}", text)
    arr_match = re.search(r"\[[\s\S]*\]", text)
    if obj_match:
        candidates.append(obj_match.group(0))
    if arr_match:
        candidates.append(arr_match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, dict) and "items" in parsed:
            return {
                "raw_items":             parsed.get("items", []),
                "model_rejected_count":  int(parsed.get("rejected_count") or 0),
                "rejection_summary":     str(parsed.get("rejection_summary") or ""),
            }
        if isinstance(parsed, list):
            return {"raw_items": parsed, "model_rejected_count": 0, "rejection_summary": ""}

    return {"raw_items": [], "model_rejected_count": 0, "rejection_summary": ""}


def _validate_structure(raw: list) -> list[dict]:
    """Keep only well-formed items; normalise optional fields."""
    required = {"title", "source_url", "summary", "relevance_score"}
    valid = []
    for item in raw:
        if not isinstance(item, dict) or not required.issubset(item.keys()):
            continue
        try:
            score = int(item["relevance_score"])
        except (ValueError, TypeError):
            continue
        item["relevance_score"] = score
        item.setdefault("source_published_date", None)
        item.setdefault("relevance_reason", "")
        item.setdefault("source_geography", "Unknown")
        item.setdefault("url_status", "unchecked")
        item.setdefault("final_url", item.get("source_url", ""))
        valid.append(item)
    return valid


# ─── URL validation ───────────────────────────────────────────────────────────

def _validate_urls_batch(items: list[dict]) -> list[dict]:
    """Check each item's URL concurrently (max 5 workers). Mutates items in-place."""
    if not items:
        return items

    urls = [item.get("source_url", "") for item in items]

    with ThreadPoolExecutor(max_workers=min(5, len(urls))) as pool:
        checks = list(pool.map(validate_url, urls))

    for item, check in zip(items, checks):
        status = check["status"]
        item["url_status"] = status
        item["final_url"]  = check.get("final_url") or item.get("source_url", "")

        # Downgrade broken/timeout items by 3 points so they sort behind valid ones
        if status in ("broken", "timeout"):
            original = item["relevance_score"]
            item["relevance_score"] = max(1, original - 3)
            item["relevance_reason"] = (
                f"[URL {status}; score reduced from {original}/10] "
                + (item.get("relevance_reason") or "")
            ).strip()

    return items


# ─── Database persistence ─────────────────────────────────────────────────────

def _save_items(items: list[dict], product_id: int, topic: str) -> int:
    """Insert research items into the database. Returns count saved."""
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for item in items:
        title = item.get("title") or item.get("source_url", "")
        rows.append((
            product_id,
            topic,
            item.get("source_url", ""),
            title,                          # legacy title column
            title,                          # source_title
            item.get("source_published_date"),
            item.get("summary", ""),
            item.get("relevance_score"),
            item.get("relevance_reason", ""),
            item.get("url_status", "unchecked"),
            item.get("final_url") or item.get("source_url", ""),
            item.get("source_geography", "Unknown"),
            now,
        ))

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO research_items
                (product_id, topic, source_url, title, source_title,
                 source_published_date, summary, relevance_score, relevance_reason,
                 url_status, final_url, source_geography, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    return len(rows)


# ─── Cost estimation ──────────────────────────────────────────────────────────

def _estimate_cost(input_tokens: int, output_tokens: int, web_searches: int) -> float:
    return round(
        input_tokens  * _INPUT_COST_PER_TOKEN
        + output_tokens * _OUTPUT_COST_PER_TOKEN
        + web_searches  * _SEARCH_COST_PER_USE,
        6,
    )


# ─── API call logging ─────────────────────────────────────────────────────────

def _log_api_call(
    topic: str,
    input_tokens: int,
    output_tokens: int,
    web_searches: int,
    cost: float,
    notes: str = "",
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    CSV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(["timestamp", "agent", "topic", "input_tokens",
                             "output_tokens", "web_searches", "est_cost_usd"])
        writer.writerow([ts, "researcher", topic, input_tokens,
                         output_tokens, web_searches, cost])

    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO api_log
                   (timestamp, agent, action, input_tokens, output_tokens,
                    web_searches, est_cost_usd, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, "researcher", topic, input_tokens, output_tokens,
                 web_searches, cost, notes),
            )
    except sqlite3.OperationalError:
        pass  # api_log not yet present; CSV is the fallback


# ─── Helpers for UI queries ───────────────────────────────────────────────────

def get_recent_topics(product_id: int, limit: int = 5) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT DISTINCT topic FROM research_items
               WHERE product_id = ? AND topic IS NOT NULL
               ORDER BY fetched_at DESC LIMIT ?""",
            (product_id, limit),
        ).fetchall()
    return [r["topic"] for r in rows]


def get_month_spend_usd() -> float:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(est_cost_usd), 0) FROM api_log WHERE timestamp LIKE ?",
                (f"{month}%",),
            ).fetchone()
        return float(row[0])
    except sqlite3.OperationalError:
        return 0.0


def get_alltime_spend_usd() -> float:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(est_cost_usd), 0) FROM api_log"
            ).fetchone()
        return float(row[0])
    except sqlite3.OperationalError:
        return 0.0
