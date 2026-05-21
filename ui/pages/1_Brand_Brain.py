"""Brand Brain — the authoritative source for all brand and product data.

Four tabs:
  A. Overview  — read-only summary of the active brand setup
  B. Edit      — edit org, product, phases, voice, audience, proof points, CTAs
  C. Partners  — manage affiliate / partner brands
  D. Seed      — one-button reset to the canonical Sportz-Well / SWPI data

Run from the project root:  streamlit run ui/app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from db.init_db import init_db
from services.database import get_connection
from services.brand_context import (
    get_active_product,
    get_brand_profile,
    get_content_rules,
    get_active_partner_brands,
)

init_db()

st.set_page_config(
    page_title="Brand Brain — Sportz-Well",
    page_icon="🧠",
    layout="wide",
)

# ─── Seed constants ───────────────────────────────────────────────────────────
# All brand-specific content lives here, not scattered through code.

_ORG_DESCRIPTION = (
    "Sports-tech SaaS company building player development and fitness intelligence "
    "platforms for Indian schools, academies, and corporates. Founded by Jitendra Sonu "
    "Jagdale — Mumbai cricketer, MCA Match Observer, Shardashram alumnus. Long-term "
    "vision: make Indian families fit again, one family at a time."
)

_SWPI_ONE_LINER = (
    "Monthly AI-powered player development intelligence platform for grassroots cricket."
)

_SWPI_DESCRIPTION = (
    "SWPI is a monthly AI-powered player development intelligence platform for grassroots "
    "cricket. It tracks attendance, match performance, weekly assessments and biomechanics "
    "— then generates professional reports that coaches share with parents. The problem it "
    "solves: coaches have no structured way to show parents what their child is actually "
    "learning. Most academies send WhatsApp voice notes. SWPI sends data-backed reports. "
    "The difference: it is built by someone who played alongside Sachin Tendulkar under "
    "Ramakant Achrekar, not a software company pretending to understand cricket."
)

_PHASES = [
    {
        "number": 1,
        "name": "Grassroots Cricket",
        "description": (
            "Cricket-only player development intelligence for schools and academies "
            "serving U10–U17 players. Focus on coach-to-parent communication and "
            "data-backed reports."
        ),
        "focus": "Cricket grassroots, schools, academies, U10–U17",
        "status": "active",
    },
    {
        "number": 2,
        "name": "Multi-Sport Athlete Assessment",
        "description": (
            "Expand the SWPI engine beyond cricket to other sports (football, badminton, "
            "athletics, etc.) for school multi-sport programs and academies."
        ),
        "focus": "Multi-sport assessment across school sports",
        "status": "planned",
    },
    {
        "number": 3,
        "name": "India Fitness Test (IFT)",
        "description": (
            "National fitness benchmark for students and employees. Targets corporates and "
            "the long-term mission of making Indian families fit again, one family at a time."
        ),
        "focus": "Family fitness, corporate wellness, IFT national benchmark",
        "status": "planned",
    },
]

_SEED_PROFILE: dict = {
    "primary_buyer": (
        "School principals and cricket academy directors. Age 35–55. Decision makers with "
        "budget authority. They care about institutional credibility and parent satisfaction."
    ),
    "secondary_buyer": (
        "Parents of U10–U17 cricketers in Tier 1 and Tier 2 Indian cities. They are paying "
        "₹3,000–8,000 per month in academy fees and want proof their investment is working."
    ),
    "end_user": (
        "Cricket coaches at schools and academies who use SWPI to generate professional "
        "player-development reports for the parents of their U10–U17 students."
    ),
    "geography": "Maharashtra first, then pan-India.",
    "voice_adjectives": ["Expert", "Structured", "Purposeful"],
    "tone_dos": [
        "Data-backed and specific — never vague",
        "Respectful of the coach's intelligence",
        "Parent-friendly without being dumbed down",
        "Confident without being arrogant",
        "India-specific — Mumbai cricket culture, school tournaments, MCA pathways",
    ],
    "tone_donts": [
        "Never hype-y or fitness-bro",
        "Never generic — no \"unlock your potential\" nonsense",
        "Never preachy about mental health",
        "Never compare to competitors by name",
        "Never use Western sports references when Indian ones exist",
    ],
    "topics_owned": [
        "Grassroots cricket development in India",
        "The gap between coaching and parent communication",
        "Mental toughness as a trainable skill — the 80/20 philosophy",
        "Mumbai cricket pathways — U14, U17, MCA",
        "AI as a coaching assistant, not a replacement for the coach",
        "Founder credibility — Achrekar academy, Tendulkar era, MCA Observer",
    ],
    "topics_avoided": [
        "National team selection politics",
        "Supplement or nutrition advice",
        "Competitor products by name",
        "Anything that positions AI as replacing human coaches",
        "Generic fitness content with no cricket context",
    ],
    "proof_points_regular": [
        "Active MCA Match Observer — currently embedded in competitive Mumbai cricket",
        "First pilot: Singhania School, Thane",
        "30+ combined years of cricket experience across the founding team",
        "AI reports generated from real match data, attendance records and biomechanical video analysis — not templates",
    ],
    "proof_points_sparing": [
        "Founder trained at Shardashram under Ramakant Achrekar alongside Sachin Tendulkar",
    ],
    "primary_cta": "Book a demo",
    "cta_url": "https://www.sportz-well.com",
    "sales_cycle_type": "Institutional-B2B",
}

_SEED_RULES = [
    {
        "key": "vision_hint_frequency",
        "value": "rare_1_in_20",
        "description": (
            "Roughly 1 in 20 posts may briefly hint at Phase 2 (multi-sport) or Phase 3 "
            "(family fitness vision). Never lead with vision content."
        ),
    },
    {
        "key": "vision_hint_instruction",
        "value": (
            "Never lead with vision content. Always anchor in Phase 1 cricket content first, "
            "then briefly hint at the larger Sportz-Well mission only if it adds depth, "
            "not when it dilutes."
        ),
        "description": "Instruction injected into agent prompts for vision-hint posts.",
    },
    {
        "key": "cta_priority",
        "value": (
            "Always end demo-focused posts with a soft CTA pointing to www.sportz-well.com. "
            "Never use 'download', 'follow', or 'subscribe' as the primary CTA — "
            "institutional sales need a demo."
        ),
        "description": "CTA discipline rule for all post drafts.",
    },
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _lines(text: str) -> list[str]:
    """Split a text block into non-empty stripped lines."""
    return [ln.strip() for ln in text.strip().splitlines() if ln.strip()]


def _csv(text: str) -> list[str]:
    """Split a comma-separated string into non-empty stripped values."""
    return [s.strip() for s in text.split(",") if s.strip()]


def _phase_badge(status: str) -> str:
    return {"active": "🟢 Active", "complete": "✅ Complete"}.get(status, "⚪ Planned")


def _freq_label_to_value() -> dict[str, str]:
    return {
        "Never": "never",
        "Rare — ~1 in 20 posts": "rare_1_in_20",
        "Occasional — ~1 in 10 posts": "occasional_1_in_10",
        "Frequent — ~1 in 5 posts": "frequent_1_in_5",
    }


def _freq_value_to_label(value: str) -> str:
    inv = {v: k for k, v in _freq_label_to_value().items()}
    return inv.get(value, "Rare — ~1 in 20 posts")


# ─── Tab A: Overview ──────────────────────────────────────────────────────────

def _render_overview() -> None:
    product = get_active_product()

    if product is None:
        st.info(
            "Nothing here yet. Go to **Seed Sportz-Well + SWPI** tab to set up the brand.",
            icon="ℹ️",
        )
        return

    prod_id = product["product_id"]
    org_id  = product["org_id"]

    profile  = get_brand_profile(prod_id)
    rules    = get_content_rules(prod_id)
    partners = get_active_partner_brands(org_id)

    with get_connection() as conn:
        phases = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM product_phases WHERE product_id = ? ORDER BY phase_number",
                (prod_id,),
            ).fetchall()
        ]
        bp_row = conn.execute(
            "SELECT updated_at FROM brand_profiles WHERE product_id = ?", (prod_id,)
        ).fetchone()

    last_update = bp_row["updated_at"][:16] if bp_row else "never"

    # --- Organisation ---
    st.subheader("Parent Organisation")
    col1, col2 = st.columns([3, 1])
    col1.markdown(f"**{product['org_name']}**")
    social_txt = "🟢 Active on social" if product["org_social_active"] else "⚫ Not on social"
    col2.markdown(social_txt)
    if product.get("org_description"):
        st.caption(product["org_description"])
    if product.get("org_website"):
        st.markdown(f"Website: {product['org_website']}")

    st.divider()

    # --- Product ---
    st.subheader("Active Product")
    col1, col2 = st.columns([3, 1])
    col1.markdown(
        f"**{product['product_name']}** — {product.get('full_name') or ''}"
    )
    prod_social = "🟢 Active on social" if product["product_social_active"] else "⚫ Not on social"
    col2.markdown(prod_social)
    if product.get("one_liner"):
        st.markdown(f"*{product['one_liner']}*")
    if product.get("product_website"):
        st.markdown(f"Website: {product['product_website']}")
    st.caption(f"Brand profile last updated: {last_update}")

    st.divider()

    # --- Phases ---
    st.subheader("Rollout Phases")
    for ph in phases:
        col1, col2 = st.columns([4, 1])
        col1.markdown(f"**Phase {ph['phase_number']} — {ph['name']}**")
        col2.markdown(_phase_badge(ph["status"]))
        if ph.get("focus"):
            st.caption(ph["focus"])

    st.divider()

    # --- Voice (compact) ---
    if profile.get("voice_adjectives") or profile.get("tone_dos") or profile.get("tone_donts"):
        st.subheader("Brand Voice")
        if profile.get("voice_adjectives"):
            st.markdown(f"**Adjectives:** {' · '.join(profile['voice_adjectives'])}")
        col1, col2 = st.columns(2)
        if profile.get("tone_dos"):
            col1.markdown("**Do**")
            for item in profile["tone_dos"]:
                col1.markdown(f"✓ {item}")
        if profile.get("tone_donts"):
            col2.markdown("**Don't**")
            for item in profile["tone_donts"]:
                col2.markdown(f"✗ {item}")
        st.divider()

    # --- Content rules ---
    if rules:
        st.subheader("Content Rules")
        rule_labels = {
            "vision_hint_frequency":   "Vision-hint frequency",
            "vision_hint_instruction": "Vision-hint instruction",
            "cta_priority":            "CTA priority",
        }
        for key, value in rules.items():
            st.markdown(f"**{rule_labels.get(key, key)}:** {value}")
        st.divider()

    # --- Partner brands ---
    st.subheader("Partner Brands")
    if not partners:
        st.caption("No partner brands yet. Add them in the **Partner Brands** tab.")
    else:
        st.caption(f"{len(partners)} active partner brand(s).")
        with st.expander("View all"):
            for pb in partners:
                st.markdown(f"**{pb['name']}** ({pb.get('category', '')})")
                if pb.get("mention_guidance"):
                    st.caption(pb["mention_guidance"])

    st.divider()

    # --- Action buttons ---
    col1, col2 = st.columns(2)
    if col1.button("Edit Brand Profile", use_container_width=True):
        st.session_state.bb_tab = 1
        st.rerun()
    if col2.button("Manage Partner Brands", use_container_width=True):
        st.session_state.bb_tab = 2
        st.rerun()


# ─── Tab B: Edit brand profile ────────────────────────────────────────────────

def _render_edit() -> None:
    product = get_active_product()

    if product is None:
        st.info(
            "Nothing to edit yet. Go to the **Seed Sportz-Well + SWPI** tab first.",
            icon="ℹ️",
        )
        return

    prod_id = product["product_id"]
    org_id  = product["org_id"]

    profile = get_brand_profile(prod_id)
    rules   = get_content_rules(prod_id)

    with get_connection() as conn:
        org_row  = dict(conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone())
        prod_row = dict(conn.execute("SELECT * FROM products WHERE id = ?", (prod_id,)).fetchone())
        phase_rows = {
            r["phase_number"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM product_phases WHERE product_id = ? ORDER BY phase_number",
                (prod_id,),
            ).fetchall()
        }

    # Reconstruct proof-points text: sparing lines get the [sparingly] prefix
    pp_lines = [p for p in profile.get("proof_points_regular", [])]
    pp_lines += [f"[sparingly] {p}" for p in profile.get("proof_points_sparing", [])]
    pp_text_default = "\n".join(pp_lines)

    st.subheader("Edit Brand Profile")
    st.caption("One **Save All Changes** button at the bottom commits everything atomically.")

    with st.form("edit_brand_profile"):

        # ── Parent Organisation ──
        st.markdown("#### Parent Organisation")
        org_name    = st.text_input("Name", value=org_row.get("name", ""))
        org_desc    = st.text_area("Description", value=org_row.get("description", ""), height=100)
        org_website = st.text_input("Website", value=org_row.get("website", ""))
        org_social  = st.checkbox(
            "Active on social media?", value=bool(org_row.get("social_active", 0))
        )

        st.divider()

        # ── Product ──
        st.markdown("#### Product (SWPI)")
        prod_full_name = st.text_input("Full name", value=prod_row.get("full_name", ""))
        prod_one_liner = st.text_input(
            "One-line positioning (max 200 chars)",
            value=prod_row.get("one_liner", ""),
            max_chars=200,
        )
        prod_desc    = st.text_area("Full description", value=prod_row.get("description", ""), height=180)
        prod_website = st.text_input("Website", value=prod_row.get("website", ""), key="prod_website")
        prod_social  = st.checkbox(
            "Active on social media?",
            value=bool(prod_row.get("social_active", 0)),
            key="prod_social_cb",
        )

        st.divider()

        # ── Phases ──
        st.markdown("#### Rollout Phases")
        STATUS_OPTIONS = ["planned", "active", "complete"]
        phase_inputs: dict[int, dict] = {}
        for n in (1, 2, 3):
            ph = phase_rows.get(n, {})
            st.markdown(f"**Phase {n}**")
            c1, c2, c3 = st.columns([3, 3, 1])
            phase_inputs[n] = {
                "name":   c1.text_input("Name", value=ph.get("name", ""), key=f"ph{n}_name"),
                "focus":  c2.text_input("Focus (one line)", value=ph.get("focus", ""), key=f"ph{n}_focus"),
                "status": c3.selectbox(
                    "Status",
                    STATUS_OPTIONS,
                    index=STATUS_OPTIONS.index(ph.get("status", "planned")),
                    key=f"ph{n}_status",
                ),
                "description": st.text_area(
                    "Description", value=ph.get("description", ""), height=80, key=f"ph{n}_desc"
                ),
            }

        st.divider()

        # ── Audience ──
        st.markdown("#### Audience")
        primary_buyer   = st.text_area("Primary buyer", value=profile.get("primary_buyer", ""), height=100)
        secondary_buyer = st.text_area("Secondary buyer / influencer", value=profile.get("secondary_buyer", ""), height=100)
        end_user        = st.text_area("End user", value=profile.get("end_user", ""), height=80)
        geography       = st.text_input("Geography", value=profile.get("geography", ""))

        st.divider()

        # ── Voice ──
        st.markdown("#### Voice")
        voice_adj      = st.text_input(
            "Voice adjectives (comma-separated)",
            value=", ".join(profile.get("voice_adjectives", [])),
        )
        tone_dos_text   = st.text_area(
            "Tone do's (one per line)", value="\n".join(profile.get("tone_dos", [])), height=130
        )
        tone_donts_text = st.text_area(
            "Tone don'ts (one per line)", value="\n".join(profile.get("tone_donts", [])), height=130
        )

        st.divider()

        # ── Topics ──
        st.markdown("#### Topics")
        topics_owned_text   = st.text_area(
            "Topics we own (one per line)", value="\n".join(profile.get("topics_owned", [])), height=130
        )
        topics_avoided_text = st.text_area(
            "Topics we avoid (one per line)", value="\n".join(profile.get("topics_avoided", [])), height=130
        )

        st.divider()

        # ── Proof Points ──
        st.markdown("#### Proof Points")
        st.caption(
            "One per line. Prefix restricted-use points with **[sparingly]** — "
            "they will be stored separately and flagged for agents."
        )
        proof_text = st.text_area("Proof points", value=pp_text_default, height=170)

        st.divider()

        # ── Call to Action ──
        st.markdown("#### Call to Action")
        primary_cta  = st.text_input("Primary CTA", value=profile.get("primary_cta", ""))
        cta_url      = st.text_input("CTA destination URL", value=profile.get("cta_url", ""))
        CYCLE_OPTIONS = ["Direct consumer", "Considered consumer", "Institutional-B2B", "Other"]
        current_cycle = profile.get("sales_cycle_type", "Institutional-B2B")
        sales_cycle = st.selectbox(
            "Sales cycle type",
            CYCLE_OPTIONS,
            index=CYCLE_OPTIONS.index(current_cycle) if current_cycle in CYCLE_OPTIONS else 2,
        )

        st.divider()

        # ── Content Rules ──
        st.markdown("#### Content Rules")
        freq_map    = _freq_label_to_value()
        freq_labels = list(freq_map.keys())
        current_freq_value = rules.get("vision_hint_frequency", "rare_1_in_20")
        current_freq_label = _freq_value_to_label(current_freq_value)
        vision_freq_label = st.selectbox(
            "Vision-hint frequency",
            freq_labels,
            index=freq_labels.index(current_freq_label) if current_freq_label in freq_labels else 1,
        )
        vision_instruction = st.text_area(
            "Vision-hint instruction",
            value=rules.get(
                "vision_hint_instruction",
                "Never lead with vision content. Always anchor in Phase 1 cricket content first.",
            ),
            height=100,
        )

        st.divider()

        submitted = st.form_submit_button("Save All Changes", type="primary")

    if submitted:
        # Parse proof points
        proof_regular, proof_sparing = [], []
        for line in _lines(proof_text):
            if line.startswith("[sparingly]"):
                proof_sparing.append(line[len("[sparingly]"):].strip())
            else:
                proof_regular.append(line)

        new_profile = {
            "primary_buyer":        primary_buyer.strip(),
            "secondary_buyer":      secondary_buyer.strip(),
            "end_user":             end_user.strip(),
            "geography":            geography.strip(),
            "voice_adjectives":     _csv(voice_adj),
            "tone_dos":             _lines(tone_dos_text),
            "tone_donts":           _lines(tone_donts_text),
            "topics_owned":         _lines(topics_owned_text),
            "topics_avoided":       _lines(topics_avoided_text),
            "proof_points_regular": proof_regular,
            "proof_points_sparing": proof_sparing,
            "primary_cta":          primary_cta.strip(),
            "cta_url":              cta_url.strip(),
            "sales_cycle_type":     sales_cycle,
        }

        with get_connection() as conn:
            conn.execute(
                "UPDATE organizations SET name=?, description=?, website=?, social_active=? WHERE id=?",
                (org_name.strip(), org_desc.strip(), org_website.strip(), int(org_social), org_id),
            )
            conn.execute(
                "UPDATE products SET full_name=?, one_liner=?, description=?, website=?, social_active=? WHERE id=?",
                (
                    prod_full_name.strip(), prod_one_liner.strip(), prod_desc.strip(),
                    prod_website.strip(), int(prod_social), prod_id,
                ),
            )
            for n, ph in phase_inputs.items():
                conn.execute(
                    """
                    INSERT INTO product_phases (product_id, phase_number, name, description, focus, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_id, phase_number) DO UPDATE SET
                        name=excluded.name, description=excluded.description,
                        focus=excluded.focus, status=excluded.status
                    """,
                    (prod_id, n, ph["name"], ph["description"], ph["focus"], ph["status"]),
                )
            conn.execute(
                """
                INSERT INTO brand_profiles (product_id, profile_data, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(product_id) DO UPDATE SET
                    profile_data=excluded.profile_data, updated_at=excluded.updated_at
                """,
                (prod_id, json.dumps(new_profile)),
            )
            vision_freq_value = freq_map[vision_freq_label]
            for rule_key, rule_value, rule_desc in [
                ("vision_hint_frequency",   vision_freq_value,            "Vision-hint frequency rule"),
                ("vision_hint_instruction", vision_instruction.strip(),   "Vision-hint instruction for agents"),
            ]:
                conn.execute(
                    """
                    INSERT INTO content_rules (product_id, rule_key, rule_value, description)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(product_id, rule_key) DO UPDATE SET
                        rule_value=excluded.rule_value, description=excluded.description
                    """,
                    (prod_id, rule_key, rule_value, rule_desc),
                )
            conn.commit()

        st.success("Brand profile saved successfully.")


# ─── Tab C: Partner brands ────────────────────────────────────────────────────

def _render_partners() -> None:
    product = get_active_product()

    if product is None:
        st.info("Seed the brand first (Tab D) before adding partner brands.", icon="ℹ️")
        return

    org_id = product["org_id"]

    with get_connection() as conn:
        all_partners = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM partner_brands WHERE organization_id = ? ORDER BY name",
                (org_id,),
            ).fetchall()
        ]

    st.subheader("Partner Brands")

    # ── Add form ──
    with st.expander("Add a new partner brand", expanded=not all_partners):
        with st.form("add_partner_form"):
            c1, c2 = st.columns(2)
            new_name     = c1.text_input("Brand name *")
            new_category = c2.text_input("Category (e.g. Sports nutrition, Apparel)")
            new_desc     = st.text_area("Description", height=80)
            new_website  = st.text_input("Website")
            new_guidance = st.text_area(
                "Mention guidance — how agents should reference this brand", height=80
            )
            new_active   = st.checkbox("Active", value=True)
            if st.form_submit_button("Add Partner Brand", type="primary"):
                if not new_name.strip():
                    st.error("Brand name is required.")
                else:
                    with get_connection() as conn:
                        conn.execute(
                            """
                            INSERT INTO partner_brands
                                (organization_id, name, category, description, website, mention_guidance, is_active)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                org_id, new_name.strip(), new_category.strip(),
                                new_desc.strip(), new_website.strip(),
                                new_guidance.strip(), int(new_active),
                            ),
                        )
                        conn.commit()
                    st.rerun()

    if not all_partners:
        st.caption("No partner brands yet. Add the first one above.")
        return

    st.divider()

    # ── Partner table ──
    # Track pending edit and pending delete in session state
    if "pb_editing" not in st.session_state:
        st.session_state.pb_editing = None
    if "pb_pending_delete" not in st.session_state:
        st.session_state.pb_pending_delete = None

    for pb in all_partners:
        pb_id   = pb["id"]
        active  = "🟢" if pb["is_active"] else "⚫"
        col_name, col_cat, col_active, col_edit, col_del = st.columns([3, 2, 1, 1, 1])
        col_name.markdown(f"**{pb['name']}**")
        col_cat.caption(pb.get("category") or "—")
        col_active.markdown(active)

        if col_edit.button("Edit", key=f"edit_{pb_id}", use_container_width=True):
            st.session_state.pb_editing       = pb_id
            st.session_state.pb_pending_delete = None
            st.rerun()

        if col_del.button("Delete", key=f"del_{pb_id}", use_container_width=True):
            st.session_state.pb_pending_delete = pb_id
            st.session_state.pb_editing        = None
            st.rerun()

        # Confirmation banner for delete
        if st.session_state.pb_pending_delete == pb_id:
            st.warning(f"Delete **{pb['name']}**? This cannot be undone.")
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("Yes, delete", key=f"confirm_del_{pb_id}", type="primary"):
                with get_connection() as conn:
                    conn.execute("DELETE FROM partner_brands WHERE id = ?", (pb_id,))
                    conn.commit()
                st.session_state.pb_pending_delete = None
                st.rerun()
            if c2.button("Cancel", key=f"cancel_del_{pb_id}"):
                st.session_state.pb_pending_delete = None
                st.rerun()

        # Inline edit form
        if st.session_state.pb_editing == pb_id:
            with st.form(f"edit_partner_{pb_id}"):
                c1, c2 = st.columns(2)
                e_name     = c1.text_input("Brand name", value=pb.get("name", ""))
                e_category = c2.text_input("Category", value=pb.get("category", ""))
                e_desc     = st.text_area("Description", value=pb.get("description", ""), height=80)
                e_website  = st.text_input("Website", value=pb.get("website", ""))
                e_guidance = st.text_area("Mention guidance", value=pb.get("mention_guidance", ""), height=80)
                e_active   = st.checkbox("Active", value=bool(pb.get("is_active", 1)))
                if st.form_submit_button("Save Changes", type="primary"):
                    with get_connection() as conn:
                        conn.execute(
                            """
                            UPDATE partner_brands
                            SET name=?, category=?, description=?, website=?,
                                mention_guidance=?, is_active=?
                            WHERE id=?
                            """,
                            (
                                e_name.strip(), e_category.strip(), e_desc.strip(),
                                e_website.strip(), e_guidance.strip(), int(e_active), pb_id,
                            ),
                        )
                        conn.commit()
                    st.session_state.pb_editing = None
                    st.rerun()

        st.divider()


# ─── Tab D: Seed ──────────────────────────────────────────────────────────────

def _do_seed() -> None:
    """Drop existing Sportz-Well / SWPI data and reinsert canonical seed rows."""
    with get_connection() as conn:
        # CASCADE removes products, phases, profiles, partner_brands, content_rules
        conn.execute("DELETE FROM organizations WHERE name = 'Sportz-Well'")

        org_id = conn.execute(
            "INSERT INTO organizations (name, description, website, social_active) VALUES (?, ?, ?, ?)",
            ("Sportz-Well", _ORG_DESCRIPTION, "https://www.sportz-well.com", 0),
        ).lastrowid

        prod_id = conn.execute(
            """
            INSERT INTO products
                (organization_id, name, full_name, one_liner, description, website, social_active, is_active_client)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                org_id, "SWPI", "Sportz-Well Performance Intelligence",
                _SWPI_ONE_LINER, _SWPI_DESCRIPTION,
                "https://www.sportz-well.com", 1, 1,
            ),
        ).lastrowid

        for ph in _PHASES:
            conn.execute(
                """
                INSERT INTO product_phases (product_id, phase_number, name, description, focus, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (prod_id, ph["number"], ph["name"], ph["description"], ph["focus"], ph["status"]),
            )

        conn.execute(
            "INSERT INTO brand_profiles (product_id, profile_data, updated_at) VALUES (?, ?, datetime('now'))",
            (prod_id, json.dumps(_SEED_PROFILE)),
        )

        for rule in _SEED_RULES:
            conn.execute(
                "INSERT INTO content_rules (product_id, rule_key, rule_value, description) VALUES (?, ?, ?, ?)",
                (prod_id, rule["key"], rule["value"], rule["description"]),
            )

        conn.commit()


def _render_seed() -> None:
    st.subheader("Seed Sportz-Well + SWPI")
    st.warning(
        "This will replace any existing Sportz-Well organisation and SWPI product data. "
        "Partner brands and content rules will be reset to defaults too.",
        icon="⚠️",
    )

    confirmed = st.checkbox(
        "I understand this will overwrite existing Sportz-Well / SWPI data."
    )

    if st.button(
        "Seed Sportz-Well + SWPI (overwrites existing)",
        type="primary",
        disabled=not confirmed,
    ):
        _do_seed()
        st.success("Seeded successfully! Switching to Overview...")
        st.session_state.bb_tab = 0
        st.rerun()


# ─── Page layout ─────────────────────────────────────────────────────────────

st.title("Brand Brain")
st.caption(
    "The authoritative source for all brand data. "
    "Every agent reads from here — never from hardcoded values."
)

TAB_LABELS = [
    "Overview",
    "Edit Brand Profile",
    "Partner Brands",
    "Seed Sportz-Well + SWPI",
]

if "bb_tab" not in st.session_state:
    st.session_state.bb_tab = 0

# Button-based tab navigation (supports programmatic switching via session state)
nav_cols = st.columns(len(TAB_LABELS))
for idx, (col, label) in enumerate(zip(nav_cols, TAB_LABELS)):
    btn_type = "primary" if st.session_state.bb_tab == idx else "secondary"
    if col.button(label, use_container_width=True, type=btn_type, key=f"nav_{idx}"):
        st.session_state.bb_tab = idx
        st.rerun()

st.divider()

active = st.session_state.bb_tab
if active == 0:
    _render_overview()
elif active == 1:
    _render_edit()
elif active == 2:
    _render_partners()
elif active == 3:
    _render_seed()
