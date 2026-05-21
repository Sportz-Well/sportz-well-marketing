"""Brand context helper — the single source of truth for all agents.

Every agent (Researcher, Strategist, Copywriter, Editor, Scheduler) MUST call
build_brand_context_prompt() to stay brand-consistent. Never hardcode brand
content inside agent code or prompts.

Public API
----------
get_active_product()               → dict with org + product + active phase, or None
get_brand_profile(product_id)      → parsed brand profile dict
get_content_rules(product_id)      → {rule_key: rule_value}
get_active_partner_brands(org_id)  → list of active partner brand dicts
build_brand_context_prompt(prod_id)→ agent-ready system prompt fragment (str)
"""

from __future__ import annotations

import json
from typing import Any

from services.database import get_connection


# ─── Data accessors ──────────────────────────────────────────────────────────

def get_active_product() -> dict[str, Any] | None:
    """Return the product flagged is_active_client=1, joined with its org and active phase.

    Returns None if no active client is configured yet.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                p.id            AS product_id,
                p.name          AS product_name,
                p.full_name,
                p.one_liner,
                p.description   AS product_description,
                p.website       AS product_website,
                p.social_active AS product_social_active,
                o.id            AS org_id,
                o.name          AS org_name,
                o.description   AS org_description,
                o.website       AS org_website,
                o.social_active AS org_social_active
            FROM products p
            JOIN organizations o ON o.id = p.organization_id
            WHERE p.is_active_client = 1
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            return None

        result = dict(row)

        phase = conn.execute(
            """
            SELECT phase_number, name, description, focus, status, activated_at
            FROM product_phases
            WHERE product_id = ? AND status = 'active'
            ORDER BY phase_number
            LIMIT 1
            """,
            (result["product_id"],),
        ).fetchone()
        result["active_phase"] = dict(phase) if phase else None

    return result


def get_brand_profile(product_id: int) -> dict[str, Any]:
    """Return the parsed brand profile JSON for a product.

    The proof_points_regular and proof_points_sparing lists are already split
    (stored separately in the JSON). Returns an empty dict if no profile exists.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT profile_data FROM brand_profiles WHERE product_id = ?",
            (product_id,),
        ).fetchone()

    if row is None:
        return {}

    return json.loads(row["profile_data"] or "{}")


def get_content_rules(product_id: int) -> dict[str, str]:
    """Return all content rules for a product as {rule_key: rule_value}.

    Returns an empty dict if no rules are configured.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT rule_key, rule_value FROM content_rules WHERE product_id = ?",
            (product_id,),
        ).fetchall()

    return {row["rule_key"]: row["rule_value"] for row in rows}


def get_active_partner_brands(organization_id: int) -> list[dict[str, Any]]:
    """Return active partner brands for an organisation. Empty list if none."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, category, description, website, mention_guidance
            FROM partner_brands
            WHERE organization_id = ? AND is_active = 1
            ORDER BY name
            """,
            (organization_id,),
        ).fetchall()

    return [dict(r) for r in rows]


# ─── Prompt builder ──────────────────────────────────────────────────────────

def build_brand_context_prompt(product_id: int) -> str:
    """Return an agent-ready system prompt fragment with the full brand context.

    Inject the returned string into the system prompt of Researcher, Strategist,
    Copywriter, and Editor agents so they stay brand-consistent without any
    hardcoded content in their code.
    """
    with get_connection() as conn:
        prod_row = conn.execute(
            """
            SELECT p.id, p.name AS product_name, p.full_name, p.one_liner,
                   p.description AS product_description,
                   p.website AS product_website, p.social_active AS product_social_active,
                   o.id AS org_id, o.name AS org_name, o.description AS org_description,
                   o.website AS org_website, o.social_active AS org_social_active
            FROM products p
            JOIN organizations o ON o.id = p.organization_id
            WHERE p.id = ?
            """,
            (product_id,),
        ).fetchone()

        if prod_row is None:
            return (
                "<!-- No brand context available. "
                "Run Brand Brain → Tab D to seed Sportz-Well / SWPI data. -->"
            )

        phase_row = conn.execute(
            """
            SELECT phase_number, name, description, focus
            FROM product_phases
            WHERE product_id = ? AND status = 'active'
            ORDER BY phase_number LIMIT 1
            """,
            (product_id,),
        ).fetchone()

    product = dict(prod_row)
    phase   = dict(phase_row) if phase_row else None
    profile = get_brand_profile(product_id)
    rules   = get_content_rules(product_id)
    partners = get_active_partner_brands(product["org_id"])

    lines: list[str] = ["## Brand Context\n"]

    # Organisation
    org_social = (
        "Active on social media."
        if product["org_social_active"]
        else "Not currently active on social media."
    )
    lines += [
        f"**Parent Organisation:** {product['org_name']}",
        product.get("org_description") or "",
        f"Social status: {org_social}",
        "",
    ]

    # Product
    prod_social = "Active" if product["product_social_active"] else "Not active"
    lines += [
        f"**Active Product:** {product['product_name']} — {product.get('full_name') or ''}",
        product.get("one_liner") or "",
        product.get("product_description") or "",
        f"Website: {product.get('product_website') or '—'} | Social: {prod_social}",
        "",
    ]

    # Active phase
    if phase:
        lines += [
            f"**Active Phase:** Phase {phase['phase_number']} — {phase['name']}",
            f"Focus: {phase.get('focus') or ''}",
            phase.get("description") or "",
            "",
        ]

    # Audience
    audience_keys = ("primary_buyer", "secondary_buyer", "end_user", "geography")
    if any(profile.get(k) for k in audience_keys):
        lines.append("**Audience**")
        if profile.get("primary_buyer"):
            lines.append(f"Primary buyer: {profile['primary_buyer']}")
        if profile.get("secondary_buyer"):
            lines.append(f"Secondary buyer / influencer: {profile['secondary_buyer']}")
        if profile.get("end_user"):
            lines.append(f"End user: {profile['end_user']}")
        if profile.get("geography"):
            lines.append(f"Geography: {profile['geography']}")
        lines.append("")

    # Voice
    if profile.get("voice_adjectives") or profile.get("tone_dos") or profile.get("tone_donts"):
        lines.append("**Voice**")
        if profile.get("voice_adjectives"):
            lines.append(f"Adjectives: {', '.join(profile['voice_adjectives'])}")
        if profile.get("tone_dos"):
            lines.append("Do:")
            lines += [f"  ✓ {item}" for item in profile["tone_dos"]]
        if profile.get("tone_donts"):
            lines.append("Don't:")
            lines += [f"  ✗ {item}" for item in profile["tone_donts"]]
        lines.append("")

    # Topics
    if profile.get("topics_owned"):
        lines.append("**Topics We Own**")
        lines += [f"- {t}" for t in profile["topics_owned"]]
        lines.append("")
    if profile.get("topics_avoided"):
        lines.append("**Topics We Avoid**")
        lines += [f"- {t}" for t in profile["topics_avoided"]]
        lines.append("")

    # Proof points
    regular = profile.get("proof_points_regular", [])
    sparing = profile.get("proof_points_sparing", [])
    if regular or sparing:
        lines.append("**Proof Points**")
        if regular:
            lines.append("Standard use:")
            lines += [f"- {p}" for p in regular]
        if sparing:
            lines.append("Use sparingly (high-credibility, limited-disclosure):")
            lines += [f"- {p}" for p in sparing]
        lines.append("")

    # Content rules
    if rules:
        rule_labels = {
            "vision_hint_frequency":   "Vision-hint frequency",
            "vision_hint_instruction": "Vision-hint instruction",
            "cta_priority":            "CTA priority rule",
        }
        lines.append("**Content Rules**")
        for key, value in rules.items():
            label = rule_labels.get(key, key)
            lines.append(f"- {label}: {value}")
        lines.append("")

    # CTA
    if profile.get("primary_cta") or profile.get("cta_url"):
        lines.append(
            f"**Primary CTA:** {profile.get('primary_cta', '')} → {profile.get('cta_url', '')}"
        )
    if profile.get("sales_cycle_type"):
        lines.append(f"**Sales Cycle:** {profile['sales_cycle_type']}")
    lines.append("")

    # Partner brands
    if partners:
        lines.append("**Active Partner Brands**")
        for pb in partners:
            lines.append(
                f"- {pb['name']} ({pb.get('category', '')}): {pb.get('mention_guidance', '')}"
            )
        lines.append("")

    return "\n".join(line for line in lines)
