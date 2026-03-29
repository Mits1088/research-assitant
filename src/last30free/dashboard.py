"""
last30free interactive dashboard — research + content generation in one place.
Launch with: python -m last30free dashboard
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import concurrent.futures

import pandas as pd
import streamlit as st

# ── page config (must be first Streamlit call) ────────────────────────────────

st.set_page_config(
    page_title="last30free",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── imports from last30free ───────────────────────────────────────────────────

from last30free.orchestrator import build_payload_for_query, save_payload_artifacts
from last30free.config import load_settings
from last30free.generator import GeneratorError, list_formats, stream_generate
from last30free.run_index import (
    latest_run_for_topic,
    latest_runs_by_topic,
    list_saved_runs,
    resolve_saved_run,
)

# ── session state init ────────────────────────────────────────────────────────

_DEFAULTS: dict[str, Any] = {
    "payload": None,       # current research payload
    "generated": {},       # {format_name: generated_text}
    "active_tab": 0,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

settings = load_settings()

# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔍 last30free")
    st.caption("Research · Synthesise · Create")
    st.divider()

    # ── Topic ──────────────────────────────────────────────────────────────────
    topic = st.text_input(
        "Topic",
        placeholder="e.g. Claude AI prompting tips",
        help="What do you want to research?",
    )

    # ── Sources ────────────────────────────────────────────────────────────────
    st.markdown("**Sources**")

    all_col, none_col = st.columns(2)
    with all_col:
        if st.button("All", use_container_width=True):
            for _s in ["reddit", "hn", "youtube", "x", "instagram", "tiktok"]:
                st.session_state[f"src_{_s}"] = True
            st.rerun()
    with none_col:
        if st.button("None", use_container_width=True):
            for _s in ["reddit", "hn", "youtube", "x", "instagram", "tiktok"]:
                st.session_state[f"src_{_s}"] = False
            st.rerun()

    src_reddit    = st.checkbox("Reddit",        value=st.session_state.get("src_reddit",    True),  key="src_reddit")
    src_hn        = st.checkbox("Hacker News",   value=st.session_state.get("src_hn",        True),  key="src_hn")
    src_youtube   = st.checkbox("YouTube",       value=st.session_state.get("src_youtube",   True),  key="src_youtube")
    src_x         = st.checkbox("X / Twitter",   value=st.session_state.get("src_x",         True),  key="src_x")
    src_instagram = st.checkbox("Instagram",     value=st.session_state.get("src_instagram", True),  key="src_instagram")
    src_tiktok    = st.checkbox("TikTok",        value=st.session_state.get("src_tiktok",    True),  key="src_tiktok")

    selected_sources = [
        s for s, on in {
            "reddit": src_reddit, "hn": src_hn, "youtube": src_youtube,
            "x": src_x, "instagram": src_instagram, "tiktok": src_tiktok,
        }.items() if on
    ] or None

    # ── Options ────────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("**Options**")

    days = st.slider("Days back", min_value=1, max_value=90, value=30, step=1)

    depth = st.radio(
        "Depth",
        options=["quick", "balanced", "deep"],
        index=1,
        horizontal=True,
        help="Quick = 10 items/source · Balanced = default · Deep = 40 items/source",
    )

    per_source_limit = st.number_input(
        "Per-source limit",
        min_value=0, max_value=100, value=0, step=5,
        help="Override fetch limit per source. 0 = use .env default.",
    )

    # ── Keyword filters ────────────────────────────────────────────────────────
    st.divider()
    st.markdown("**Keyword filters** *(AND logic)*")
    filters_raw = st.text_input(
        "Keywords",
        placeholder="breaking, GPT-4",
        label_visibility="collapsed",
        help="Comma-separated. All keywords must appear in a result to include it.",
    )

    # ── Save ───────────────────────────────────────────────────────────────────
    save_run = st.checkbox("Save run to disk", value=False)

    st.divider()
    run_btn = st.button(
        "▶  Run Research",
        type="primary",
        use_container_width=True,
        disabled=not bool(topic.strip()),
    )

# ── execute research ──────────────────────────────────────────────────────────

if run_btn and topic.strip():
    filters = [kw.strip() for kw in filters_raw.split(",") if kw.strip()] or None
    psl = int(per_source_limit) if per_source_limit > 0 else None

    with st.spinner(f"Researching **{topic}** across {len(selected_sources or [])} sources…"):
        try:
            # Run in a dedicated thread so asyncio.run() (used by Playwright adapters)
            # gets a clean thread with no existing event loop.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    build_payload_for_query,
                    raw_query=topic,
                    settings=settings,
                    days=days,
                    sources=selected_sources,
                    filters=filters,
                    per_source_limit=psl,
                    quick=(depth == "quick"),
                    deep=(depth == "deep"),
                )
                payload = future.result()
        except Exception as exc:
            st.error(f"Research failed: {exc}")
            st.stop()

    if save_run:
        payload = save_payload_artifacts(
            settings=settings,
            payload=payload,
            raw_query=topic,
            argv_list=["dashboard"],
        )

    st.session_state["payload"] = payload
    st.session_state["generated"] = {}

# ── tabs ──────────────────────────────────────────────────────────────────────

tab_results, tab_generate, tab_history = st.tabs([
    "📊  Research Results",
    "✍️  Generate Content",
    "🗂️  Run History",
])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — Research Results
# ════════════════════════════════════════════════════════════════════════════════

with tab_results:
    payload: dict[str, Any] | None = st.session_state.get("payload")

    if payload is None:
        st.markdown("### Welcome to last30free")
        st.info(
            "👈 Enter a topic in the sidebar and click **Run Research** to fetch "
            "trending content from Reddit, HN, YouTube, X, Instagram, and TikTok."
        )
        st.stop()

    intent  = payload.get("intent", {})
    runtime = payload.get("runtime", {})
    synth   = payload.get("synthesis", {})
    merged  = payload.get("merged", {})

    # ── top metrics ────────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Topic",        intent.get("topic", "—"))
    m2.metric("Items found",  merged.get("count", 0))
    m3.metric("Days window",  runtime.get("days", 0))
    m4.metric("Depth",        runtime.get("depth", "—"))
    m5.metric("Status",       payload.get("status", "—"))

    st.divider()

    # ── source execution table ─────────────────────────────────────────────────
    st.subheader("Source execution")
    src_rows = []
    for src in ("reddit", "hn", "youtube", "x", "instagram", "tiktok"):
        r = payload.get("results", {}).get(src, {})
        if r.get("status") == "not_requested":
            continue
        status = r.get("status", "")
        badge = "✅" if status == "ok" else ("⚠️" if status == "partial" else "❌" if status == "error" else "⏭️")
        src_rows.append({
            "Source":  src,
            "Status":  f"{badge} {status}",
            "Items":   r.get("count", 0),
            "Error":   r.get("error") or "",
        })
    if src_rows:
        st.dataframe(pd.DataFrame(src_rows), use_container_width=True, hide_index=True)

    # ── synthesis ──────────────────────────────────────────────────────────────
    headline = str(synth.get("headline") or "")
    if headline:
        st.divider()
        st.subheader("What the research found")
        st.info(headline)

    points = synth.get("summary_points", [])
    patterns = synth.get("patterns", [])

    if points or patterns:
        col_pts, col_pats = st.columns(2)

        with col_pts:
            if points:
                with st.expander("Key takeaways", expanded=True):
                    for p in points:
                        st.markdown(f"- {p}")

        with col_pats:
            if patterns:
                with st.expander("Recurring patterns", expanded=True):
                    pat_rows = [
                        {
                            "Keyword":  p.get("keyword", ""),
                            "Mentions": p.get("mentions", 0),
                            "Sources":  p.get("source_count", 0),
                        }
                        for p in patterns
                    ]
                    st.dataframe(pd.DataFrame(pat_rows), use_container_width=True, hide_index=True)

    # ── merged results table ───────────────────────────────────────────────────
    items = merged.get("items", [])
    if not items:
        st.warning("No results found for this query in the selected time window.")
    else:
        st.divider()
        st.subheader(f"Top {len(items)} results")

        rows = []
        for idx, item in enumerate(items, start=1):
            rows.append({
                "#":       idx,
                "Source":  item.get("source", ""),
                "Score":   round(float(item.get("score", 0)), 2),
                "Date":    str(item.get("created_at", ""))[:10],
                "Title":   item.get("title", ""),
                "URL":     item.get("url", ""),
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.NumberColumn("Score", format="%.2f"),
                "URL":   st.column_config.LinkColumn("URL", display_text="open ↗"),
            },
        )

    # ── saved artifacts note ───────────────────────────────────────────────────
    artifacts = payload.get("artifacts")
    if artifacts:
        st.divider()
        run_id = payload.get("index_entry", {}).get("run_id", "")
        st.success(
            f"Run saved · ID: `{run_id}` · "
            f"[Report]({artifacts.get('report_path', '')}) · "
            f"[Payload]({artifacts.get('payload_path', '')})"
        )

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Generate Content
# ════════════════════════════════════════════════════════════════════════════════

with tab_generate:
    payload = st.session_state.get("payload")

    if payload is None:
        st.info("Run a research query first, then come here to generate content.")
        st.stop()

    intent = payload.get("intent", {})
    topic_label = intent.get("topic", "")
    item_count  = payload.get("merged", {}).get("count", 0)

    st.caption(f"Generating from: **{topic_label}** · {item_count} research items")
    st.divider()

    # ── format picker + generate button ───────────────────────────────────────
    fmt_col, btn_col = st.columns([3, 1])
    with fmt_col:
        fmt = st.selectbox(
            "Content format",
            options=list_formats(),
            format_func=lambda x: {
                "facebook-post":       "📘 Facebook Post",
                "instagram-carousel":  "🎠 Instagram Carousel",
                "instagram-reel":      "🎬 Instagram Reel Script",
                "youtube-script":      "▶️  YouTube Script",
            }.get(x, x),
        )
    with btn_col:
        st.write("")
        st.write("")
        gen_btn = st.button("✨ Generate", type="primary", use_container_width=True)

    # ── output area ────────────────────────────────────────────────────────────
    generated: dict[str, str] = st.session_state.get("generated", {})

    if gen_btn:
        st.session_state["generated"].pop(fmt, None)  # clear previous for this format
        output_area = st.empty()
        try:
            result = output_area.write_stream(
                stream_generate(payload=payload, format_name=fmt)
            )
            st.session_state["generated"][fmt] = result
        except GeneratorError as exc:
            st.error(f"Generation failed: {exc}")

    elif fmt in generated:
        # show previously generated content for this format
        st.markdown(generated[fmt])
        col_regen, col_copy = st.columns([1, 4])
        with col_regen:
            if st.button("🔄 Regenerate"):
                del st.session_state["generated"][fmt]
                st.rerun()

    # ── save generated to run dir ──────────────────────────────────────────────
    if fmt in st.session_state.get("generated", {}):
        artifacts = payload.get("artifacts")
        if artifacts:
            run_dir = Path(str(artifacts.get("run_dir", "") or ""))
            if run_dir.exists():
                save_path = run_dir / f"generated_{fmt.replace('-', '_')}.md"
                st.divider()
                if st.button("💾 Save to run directory"):
                    save_path.write_text(st.session_state["generated"][fmt], encoding="utf-8")
                    st.success(f"Saved to `{save_path}`")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — Run History
# ════════════════════════════════════════════════════════════════════════════════

with tab_history:
    entries = list_saved_runs(settings.app.output_dir, limit=50)

    if not entries:
        st.info(
            "No saved runs yet. Run a query with **Save run to disk** checked "
            "in the sidebar to start building history."
        )
    else:
        st.subheader(f"{len(entries)} saved runs")

        rows = []
        for e in entries:
            rows.append({
                "Run ID":    e.get("run_id", ""),
                "Topic":     e.get("topic", ""),
                "Date":      str(e.get("generated_at_utc", ""))[:19].replace("T", " "),
                "Status":    e.get("status", ""),
                "Items":     e.get("merged_items", 0),
                "Sources":   ", ".join(e.get("selected_sources", []) or []),
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.markdown("**Load a run into the dashboard**")
        load_ref = st.text_input(
            "Run ID or topic",
            placeholder="Paste a Run ID from the table above, or type part of a topic",
            label_visibility="collapsed",
        )

        if st.button("Load Run", disabled=not bool(load_ref.strip())):
            manifest = resolve_saved_run(settings.app.output_dir, load_ref.strip())
            if manifest is None:
                st.error(f"No run found matching: `{load_ref}`")
            else:
                files = manifest.get("files", {})
                pp = Path(str(files.get("payload_path", "") or ""))
                if pp.exists():
                    loaded = json.loads(pp.read_text(encoding="utf-8"))
                    st.session_state["payload"] = loaded
                    st.session_state["generated"] = {}
                    run_id = manifest.get("run_id", "")
                    st.success(f"Loaded run `{run_id}` — switch to the **Research Results** tab to view.")
                    st.rerun()
                else:
                    st.error("Payload file not found for this run.")
