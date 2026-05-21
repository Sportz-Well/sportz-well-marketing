"""Smoke tests for agents.editor._parse_editor_json.

These tests lock in the parser's behavior across the four extraction strategies:
    1. Markdown code fence extraction
    2. Whole-string fence stripping
    3. Brace-extract (first '{' to last '}')
    4. Multi-block raw_decode scan (last valid wins)

The 8 numbered tests below mirror the inline smoke tests run during the editor
hardening session on 2026-05-18. Tests 9 and 10 are defensive additions covering
empty input and a structurally valid but semantically wrong response.

Run from project root:
    pytest tests/test_editor_parser.py -v
"""

from __future__ import annotations

import json

import pytest

from agents.editor import _parse_editor_json


# ─── Helper ──────────────────────────────────────────────────────────────────

def _sample_issue() -> dict:
    """A minimal valid issue object, used as filler inside test inputs."""
    return {
        "code":     "HYPE_WORD",
        "severity": "hard",
        "field":    "body",
        "evidence": "transformative",
        "message":  "Banned hype word.",
    }


# ─── Test 1: single clean block ──────────────────────────────────────────────

def test_single_clean_block_empty_issues():
    """The simplest happy path: model returns exactly {"issues": []}."""
    raw = '{"issues": []}'
    result = _parse_editor_json(raw)
    assert result is not None
    assert result == {"issues": []}


def test_single_clean_block_with_issue():
    """Single block, one issue object inside."""
    raw = json.dumps({"issues": [_sample_issue()]})
    result = _parse_editor_json(raw)
    assert result is not None
    assert len(result["issues"]) == 1
    assert result["issues"][0]["code"] == "HYPE_WORD"


# ─── Test 2: trailing comma ──────────────────────────────────────────────────

def test_trailing_comma_in_array():
    """JSON.loads rejects trailing commas; parser's regex must strip them."""
    raw = '{"issues": [{"code":"X","severity":"hard","field":"body","evidence":"e","message":"m"},]}'
    result = _parse_editor_json(raw)
    assert result is not None
    assert len(result["issues"]) == 1


def test_trailing_comma_in_object():
    """Trailing comma after the last object property."""
    raw = '{"issues": [],}'
    result = _parse_editor_json(raw)
    assert result is not None
    assert result == {"issues": []}


# ─── Test 3: empty issues with surrounding prose ─────────────────────────────

def test_empty_issues_with_prose_prefix():
    """Model prefixes JSON with prose despite system prompt instructions."""
    raw = 'Here is my review:\n\n{"issues": []}'
    result = _parse_editor_json(raw)
    assert result is not None
    assert result == {"issues": []}


def test_empty_issues_with_prose_suffix():
    """Model adds prose after JSON."""
    raw = '{"issues": []}\n\nLet me know if you need anything else.'
    result = _parse_editor_json(raw)
    assert result is not None
    assert result == {"issues": []}


# ─── Test 4: markdown code fence ─────────────────────────────────────────────

def test_markdown_fence_with_json_label():
    """Model wraps response in ```json ... ``` despite system prompt instructions."""
    raw = '```json\n{"issues": []}\n```'
    result = _parse_editor_json(raw)
    assert result is not None
    assert result == {"issues": []}


def test_markdown_fence_no_label():
    """Bare ``` fence without 'json' label."""
    raw = '```\n{"issues": [' + json.dumps(_sample_issue()) + ']}\n```'
    result = _parse_editor_json(raw)
    assert result is not None
    assert len(result["issues"]) == 1


# ─── Test 5: multi-block pretty-printed (self-correction pattern) ────────────

def test_multi_block_pretty_printed():
    """The 'Wait, let me reconsider' pattern that Strategy 4 was built for.

    Model emits a pretty-printed block, then prose, then a corrected
    pretty-printed block. The last block must win.
    """
    first_issue  = _sample_issue()
    second_issue = {**_sample_issue(), "code": "URL_FORMAT", "field": "cta_line"}

    raw = (
        '{\n'
        '  "issues": [\n'
        '    ' + json.dumps(first_issue) + '\n'
        '  ]\n'
        '}\n\n'
        'Wait — I need to re-evaluate. The cta_line issue is more severe.\n\n'
        '{\n'
        '  "issues": [\n'
        '    ' + json.dumps(first_issue) + ',\n'
        '    ' + json.dumps(second_issue) + '\n'
        '  ]\n'
        '}'
    )
    result = _parse_editor_json(raw)
    assert result is not None
    assert len(result["issues"]) == 2  # Last block has both issues
    codes = [i["code"] for i in result["issues"]]
    assert "URL_FORMAT" in codes


# ─── Test 6: multi-block compact ─────────────────────────────────────────────

def test_multi_block_compact():
    """Same self-correction pattern but both blocks compact (no whitespace)."""
    raw = (
        '{"issues":[' + json.dumps(_sample_issue()) + ']}'
        ' Hmm, on reflection that\'s wrong. '
        '{"issues":[]}'
    )
    result = _parse_editor_json(raw)
    assert result is not None
    assert result == {"issues": []}  # Last block wins


# ─── Test 7: multi-block ending clean ────────────────────────────────────────

def test_multi_block_first_flagged_then_clean():
    """Model first flags issues, then prose reverses course, then emits clean.

    This is the exact pattern that prompted Strategy 4: the human-meaningful
    answer is always the LAST block.
    """
    raw = (
        '{"issues": [' + json.dumps(_sample_issue()) + ']}\n'
        '\n'
        'Actually, looking again, "transformative" is inside a direct quote, '
        'which the DO NOT FLAG rule explicitly excludes. Correcting:\n'
        '\n'
        '{"issues": []}'
    )
    result = _parse_editor_json(raw)
    assert result is not None
    assert result == {"issues": []}


# ─── Test 8: truly malformed ─────────────────────────────────────────────────

def test_truly_malformed_returns_none():
    """No recoverable JSON anywhere — parser must return None, not raise."""
    raw = '{not even close to json - random text - {{{{ broken'
    result = _parse_editor_json(raw)
    assert result is None


def test_plain_prose_no_json_returns_none():
    """Pure prose, no JSON braces — None, not a crash."""
    raw = "I cannot review this draft because the input format is unclear."
    result = _parse_editor_json(raw)
    assert result is None


# ─── Test 9: empty string input (defensive) ──────────────────────────────────

def test_empty_string_returns_none():
    """An empty response from the model must not crash the parser."""
    assert _parse_editor_json("") is None
    assert _parse_editor_json("   ") is None
    assert _parse_editor_json("\n\n\n") is None


# ─── Test 10: structurally valid JSON missing "issues" key (defensive) ───────

def test_valid_json_without_issues_key_returns_none():
    """Model returns parseable JSON but without the required 'issues' key.

    Success criterion for the parser is presence of 'issues', not just valid JSON.
    """
    raw = '{"verdict": "clean", "reviewed_at": "2026-05-19"}'
    result = _parse_editor_json(raw)
    assert result is None


def test_valid_json_array_not_object_returns_none():
    """A JSON array at the top level lacks the 'issues' key — must return None."""
    raw = '[{"code": "HYPE_WORD"}]'
    result = _parse_editor_json(raw)
    assert result is None


# ─── Additional edge cases worth locking in ──────────────────────────────────

def test_issues_key_present_value_null():
    """Documented known gap: {"issues": null} parses but _validate_issues rejects.

    This test pins the CURRENT behavior so we notice if we change it later.
    The parser returns the dict; the validator (separately tested) handles null.
    """
    raw = '{"issues": null}'
    result = _parse_editor_json(raw)
    assert result is not None
    assert result == {"issues": None}


def test_multi_block_all_invalid_falls_through():
    """If every {"issues" candidate fails raw_decode, parser returns None."""
    raw = '{"issues": [broken {"issues": also broken'
    result = _parse_editor_json(raw)
    assert result is None