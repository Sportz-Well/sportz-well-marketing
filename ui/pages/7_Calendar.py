"""
Calendar page — Sportz-Well Marketing Studio
Prompt 8: Scheduler Agent UI

Three tabs:
  Tab 1 — Schedule a Draft   : pick approved draft → pick date/time → confirm
  Tab 2 — Calendar View      : week/month grid, mark as posted, unschedule
  Tab 3 — Pipeline Overview  : approved drafts: scheduled vs unscheduled counts
"""

import streamlit as st
from datetime import datetime, date, timedelta
import calendar as cal_module

from services.brand_context import get_active_product
from agents.scheduler import (
    schedule_draft,
    unschedule,
    reschedule,
    mark_as_posted,
    get_scheduled_drafts,
    get_pipeline_summary,
    get_approved_unscheduled_drafts,
)

# ─── page config ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Calendar — Sportz-Well",
    page_icon="🗓",
    layout="wide",
)

# ─── brand context ────────────────────────────────────────────────────────────

product = get_active_product()
if not product:
    st.error("No active product found. Go to Brand Brain and set an active product.")
    st.stop()

product_id   = product["product_id"]
product_name = product["product_name"]

# ─── header ──────────────────────────────────────────────────────────────────

st.title("🗓 Content Calendar")
st.caption(f"Product: **{product_name}** · V1 model: draft here → copy-paste into Meta Business Suite")
st.divider()

# ─── tabs ─────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs([
    "📌 Schedule a Draft",
    "📅 Calendar View",
    "📊 Pipeline Overview",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Schedule a Draft
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    st.subheader("Schedule an Approved Draft")
    st.caption("Only approved drafts that are not yet scheduled appear here.")

    drafts = get_approved_unscheduled_drafts(product_id)

    if not drafts:
        st.info(
            "No approved, unscheduled drafts found. "
            "Go to **Drafts** or **Editor** pages to approve drafts first."
        )
    else:
        # Build dropdown labels
        def _draft_label(d: dict) -> str:
            platform = d["platform"].capitalize()
            title    = d["angle_title"] or "Untitled angle"
            variant  = d["variant_number"]
            fmt      = d["content_format"].replace("_", " ").title()
            return f"Draft #{d['draft_id']} · {platform} V{variant} · {fmt} · {title}"

        draft_options = {_draft_label(d): d for d in drafts}

        selected_label = st.selectbox(
            "Pick a draft to schedule",
            options=list(draft_options.keys()),
        )
        selected_draft = draft_options[selected_label]

        # Show draft preview
        with st.expander("👀 Preview selected draft", expanded=False):
            st.markdown(f"**Platform:** {selected_draft['platform'].capitalize()}")
            st.markdown(f"**Format:** {selected_draft['content_format'].replace('_',' ').title()}")
            if selected_draft.get("headline"):
                st.markdown(f"**Hook:** {selected_draft['headline']}")
            st.markdown("**Body:**")
            st.text(selected_draft["body"][:500] + ("…" if len(selected_draft["body"]) > 500 else ""))

        st.divider()

        # Date and time pickers
        col1, col2 = st.columns(2)
        with col1:
            post_date = st.date_input(
                "📅 Post date",
                value=date.today() + timedelta(days=1),
                min_value=date.today(),
            )
        with col2:
            post_time = st.time_input(
                "🕐 Post time (your local time)",
                value=datetime.now().replace(hour=9, minute=0, second=0, microsecond=0).time(),
            )

        scheduled_for = f"{post_date}T{post_time.strftime('%H:%M:%S')}"

        st.markdown(f"**Scheduled for:** `{scheduled_for}`")

        if st.button("✅ Confirm Schedule", type="primary", use_container_width=True):
            result = schedule_draft(selected_draft["draft_id"], scheduled_for)
            if result["ok"]:
                st.success(
                    f"Draft #{selected_draft['draft_id']} scheduled for **{scheduled_for}** "
                    f"(Schedule ID: #{result['schedule_id']})"
                )
                st.rerun()
            else:
                st.error(f"Failed: {result['error']}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Calendar View
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.subheader("Calendar View")

    # ── view mode toggle ──
    view_mode = st.radio(
        "View",
        ["This Week", "This Month", "Custom Range"],
        horizontal=True,
    )

    today = date.today()

    if view_mode == "This Week":
        # Monday to Sunday of current week
        start = today - timedelta(days=today.weekday())
        end   = start + timedelta(days=6)

    elif view_mode == "This Month":
        start = today.replace(day=1)
        last_day = cal_module.monthrange(today.year, today.month)[1]
        end = today.replace(day=last_day)

    else:  # Custom Range
        col_a, col_b = st.columns(2)
        with col_a:
            start = st.date_input("From", value=today, key="custom_start")
        with col_b:
            end = st.date_input("To", value=today + timedelta(days=13), key="custom_end")

    st.caption(f"Showing: **{start.strftime('%d %b %Y')}** → **{end.strftime('%d %b %Y')}**")
    st.divider()

    entries = get_scheduled_drafts(str(start), str(end))

    if not entries:
        st.info("No posts scheduled in this range.")
    else:
        # Group by date
        grouped: dict[str, list] = {}
        for entry in entries:
            day_key = entry["scheduled_for"][:10]  # YYYY-MM-DD
            grouped.setdefault(day_key, []).append(entry)

        for day_key in sorted(grouped.keys()):
            day_entries = grouped[day_key]
            day_label   = datetime.strptime(day_key, "%Y-%m-%d").strftime("%A, %d %b %Y")

            st.markdown(f"### 📅 {day_label}")

            for entry in day_entries:
                schedule_id  = entry["schedule_id"]
                posted       = entry["posted_at"] is not None
                platform     = entry["platform"].capitalize()
                variant      = entry["variant_number"]
                fmt          = entry["content_format"].replace("_", " ").title()
                angle_title  = entry["angle_title"] or "Untitled"
                time_str     = entry["scheduled_for"][11:16]  # HH:MM

                # Status badge
                if posted:
                    badge = "✅ Posted"
                    card_color = "#e8f5e9"
                else:
                    badge = "⏳ Pending"
                    card_color = "#fff8e1"

                with st.container(border=True):
                    col_info, col_actions = st.columns([3, 1])

                    with col_info:
                        st.markdown(
                            f"**{time_str}** · {platform} V{variant} · {fmt}  \n"
                            f"📌 _{angle_title}_  \n"
                            f"{badge}"
                        )
                        if posted:
                            st.caption(f"Posted at: {entry['posted_at']}")

                    with col_actions:
                        if not posted:
                            # Mark as posted
                            if st.button(
                                "✅ Mark Posted",
                                key=f"post_{schedule_id}",
                                use_container_width=True,
                            ):
                                result = mark_as_posted(schedule_id)
                                if result["ok"]:
                                    st.success("Marked as posted!")
                                    st.rerun()
                                else:
                                    st.error(result["error"])

                            # Reschedule
                            with st.expander("🔄 Reschedule"):
                                new_date = st.date_input(
                                    "New date",
                                    value=datetime.strptime(entry["scheduled_for"][:10], "%Y-%m-%d").date(),
                                    key=f"rd_{schedule_id}",
                                )
                                new_time = st.time_input(
                                    "New time",
                                    value=datetime.strptime(entry["scheduled_for"][11:19], "%H:%M:%S").time(),
                                    key=f"rt_{schedule_id}",
                                )
                                if st.button("Confirm Reschedule", key=f"rc_{schedule_id}"):
                                    new_dt = f"{new_date}T{new_time.strftime('%H:%M:%S')}"
                                    result = reschedule(schedule_id, new_dt)
                                    if result["ok"]:
                                        st.success(f"Rescheduled to {new_dt}")
                                        st.rerun()
                                    else:
                                        st.error(result["error"])

                            # Unschedule
                            if st.button(
                                "🗑 Unschedule",
                                key=f"del_{schedule_id}",
                                use_container_width=True,
                                type="secondary",
                            ):
                                result = unschedule(schedule_id)
                                if result["ok"]:
                                    st.warning("Removed from schedule.")
                                    st.rerun()
                                else:
                                    st.error(result["error"])

            st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Pipeline Overview
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("Pipeline Overview")
    st.caption("Approved drafts: how many are scheduled vs still waiting.")

    summary = get_pipeline_summary(product_id)

    # ── top KPI row ──
    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "✅ Approved Drafts",
        summary["total_approved"],
        help="Drafts with status = approved",
    )
    col2.metric(
        "📅 Scheduled (pending)",
        summary["scheduled_pending"],
        help="Approved drafts on the calendar, not yet posted",
    )
    col3.metric(
        "📭 Not Scheduled",
        summary["unscheduled"],
        help="Approved drafts with no calendar entry yet",
    )
    col4.metric(
        "📤 Posted This Month",
        summary["posted_this_month"],
        help=f"Posts marked as manually posted in {datetime.now().strftime('%B %Y')}",
    )

    st.divider()

    # ── platform breakdown ──
    breakdown = summary.get("platform_breakdown", {})

    if breakdown:
        st.markdown("#### Scheduled posts by platform (pending only)")
        bcol1, bcol2 = st.columns(2)

        ig_count = breakdown.get("instagram", 0)
        fb_count = breakdown.get("facebook", 0)

        bcol1.metric("📸 Instagram", ig_count)
        bcol2.metric("👥 Facebook",  fb_count)

    else:
        st.info("No pending scheduled posts.")

    st.divider()

    # ── health check ──
    st.markdown("#### Health Check")

    total    = summary["total_approved"]
    sched    = summary["scheduled_pending"]
    unsched  = summary["unscheduled"]
    posted   = summary["posted_this_month"]

    if total == 0:
        st.warning(
            "⚠️ No approved drafts yet. "
            "Go to **Editor** page to review and approve drafts."
        )
    elif unsched == 0 and sched == 0 and posted > 0:
        st.success("🎉 All approved drafts have been posted this month. Time to generate more!")
    elif unsched > 0:
        st.warning(
            f"⚠️ **{unsched}** approved draft(s) are not scheduled. "
            "Go to **Schedule a Draft** tab to add them to the calendar."
        )
    else:
        st.success(
            f"✅ All {total} approved draft(s) are on the calendar."
        )

    # ── next 7 days snapshot ──
    st.divider()
    st.markdown("#### Next 7 Days")

    next_week_entries = get_scheduled_drafts(
        str(today),
        str(today + timedelta(days=6)),
    )
    pending_next_week = [e for e in next_week_entries if e["posted_at"] is None]

    if not pending_next_week:
        st.info("Nothing scheduled in the next 7 days.")
    else:
        for e in pending_next_week:
            day_label = datetime.strptime(e["scheduled_for"][:10], "%Y-%m-%d").strftime("%a %d %b")
            time_str  = e["scheduled_for"][11:16]
            platform  = e["platform"].capitalize()
            title     = e["angle_title"] or "Untitled"
            st.markdown(
                f"• **{day_label} {time_str}** — {platform} · _{title}_"
            )