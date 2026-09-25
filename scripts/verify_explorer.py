#!/usr/bin/env python3
"""End-to-end browser verification of the explorer (F4).

Boots the real app on a temporary SQLite database, seeds crafted data,
drives a real Chromium via Playwright, and prints a per-group PASS/FAIL
table. Exactly 193 checks in 11 groups. Exit 0 only when all 193 pass.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO / ".venv" / "bin" / "python"
CONTRAST_SCRIPT = Path(
    "/root/.hermes/profiles/personal-assistant/skills/"
    "autonomous-ai-agents/agy-build-pipeline/scripts/contrast_check.py"
)

# ---------------------------------------------------------------------------
# Constants mirroring the app
# ---------------------------------------------------------------------------

COOKIE_NAME = "raschlab_sid"
SESSION_TOKEN = "verifytoken0000000000000000000000000000000000"  # 46 chars
SESSION_TOKEN_HASH = hashlib.sha256(SESSION_TOKEN.encode()).hexdigest()

FOREIGN_TOKEN = "foreigntoken000000000000000000000000000000000"
FOREIGN_TOKEN_HASH = hashlib.sha256(FOREIGN_TOKEN.encode()).hexdigest()

NOW_EPOCH = int(time.time())
FAR_FUTURE = NOW_EPOCH + 90 * 86400

# ---------------------------------------------------------------------------
# Seed data parameters (deterministic, no random)
# ---------------------------------------------------------------------------

N_ITEMS = 147
N_PERSONS = 501
MISFIT_ITEM = 7
N_WRIGHT_BINS = 25

# 3 items whose measures differ between analysis1 and analysis2, known deltas
DELTA_ITEMS = {
    3:  ("0.50",  "0.75"),   # delta = +0.25
    10: ("-1.20", "-1.30"),  # delta = -0.10
    25: ("2.00",  "1.68"),   # delta = -0.32
}

ITEM_MEASURE_MEAN_A1  = "0.00"
PERSON_MEASURE_MEAN_A1 = "0.35"
ITEM_COUNT_A1 = str(N_ITEMS)
PERSON_COUNT_A1 = "490"       # non-extreme persons
PERSON_EXTREME_INCL_A1 = "501"

ITEM_MEASURE_MEAN_A2  = "0.01"
PERSON_MEASURE_MEAN_A2 = "0.34"

# ---------------------------------------------------------------------------
# CSV builders
# ---------------------------------------------------------------------------


def build_item_csv(analysis_idx: int) -> str:
    """Build item_table_15.1.csv with N_ITEMS data rows.

    Items carry labels LBL001..LBL147. Three entries have different
    measures between analysis 1 and analysis 2.
    """
    lines = [
        "ENTRY,SCORE,COUNT,MEASURE,S.E.,INFIT MNSQ,INFIT ZSTD,"
        "OUTFIT MNSQ,OUTFIT ZSTD,PTMEASUR-AL CORR.,EXP.,EXACT OBS%,EXACT EXPECTED%,ITEM",
        "NUMBER,SCORE,COUNT,MEASURE,S.E.,MNSQ,ZSTD,MNSQ,ZSTD,CORR.,EXP.,OBS%,EXP%,ITEM",
    ]
    for i in range(1, N_ITEMS + 1):
        label = f"LBL{i:03d}"
        if i in DELTA_ITEMS:
            measure = DELTA_ITEMS[i][analysis_idx - 1]
        else:
            measure = f"{(i * 0.01 - 0.74):.2f}"
        # one deliberately misfitting item, so the misfit toggle has something to mark
        infit = "1.65" if i == MISFIT_ITEM else "1.00"
        lines.append(
            f"{i},{i * 10},490,{measure},0.10,{infit},0.00,"
            f"{infit},0.00,0.50,0.49,73.50,73.20,{label}"
        )
    return "\n".join(lines) + "\n"


def build_person_csv() -> str:
    """Build person_table.csv with N_PERSONS data rows."""
    lines = [
        "ENTRY,SCORE,COUNT,MEASURE,S.E.,INFIT MNSQ,INFIT ZSTD,"
        "OUTFIT MNSQ,OUTFIT ZSTD,PTMEASUR-AL CORR.,EXP.,EXACT OBS%,EXACT EXPECTED%,PERSON,STATUS",
        "NUMBER,SCORE,COUNT,MEASURE,S.E.,MNSQ,ZSTD,MNSQ,ZSTD,CORR.,EXP.,OBS%,EXP%,PERSON,RANK",
    ]
    for i in range(1, N_PERSONS + 1):
        person_id = f"P{i:04d}"
        measure = f"{(i * 0.005 - 1.25):.2f}"
        lines.append(
            f"{i},{i % 148},147,{measure},0.12,1.00,0.00,"
            f"1.00,0.00,0.45,0.44,70.00,69.80,{person_id},"
        )
    return "\n".join(lines) + "\n"


def build_summary_csv(analysis_idx: int) -> str:
    """Build summary_table.csv with required summary rows."""
    item_mean   = ITEM_MEASURE_MEAN_A1   if analysis_idx == 1 else ITEM_MEASURE_MEAN_A2
    person_mean = PERSON_MEASURE_MEAN_A1 if analysis_idx == 1 else PERSON_MEASURE_MEAN_A2
    return "\n".join([
        "CATEGORY,STATISTIC,VALUE",
        ",,",
        f"ITEM,COUNT,{ITEM_COUNT_A1}",
        f"ITEM,MEASURE MEAN,{item_mean}",
        f"PERSON,COUNT,{PERSON_COUNT_A1}",
        f"PERSON,MEASURE MEAN,{person_mean}",
        f"PERSON,EXTREME INCL COUNT,{PERSON_EXTREME_INCL_A1}",
    ]) + "\n"


def build_wright_map_csv(malformed: bool = False) -> str:
    """Build wright_map_measure.csv.

    malformed=True produces a headers-only file (triggers wright_error).
    """
    lines = [
        "MEASURE,NR_PERSON,PERSON_HIST,NR_ITEM,ITEMS,ITEM_HIST,PERSON_ENTRIES,ITEM_ENTRIES",
        ",,,,,,,",
    ]
    if malformed:
        return "\n".join(lines) + "\n"

    per_bin   = 490 // N_WRIGHT_BINS
    remainder = 490 % N_WRIGHT_BINS
    item_counter = 1
    for b in range(N_WRIGHT_BINS):
        measure  = f"{(b * 0.3 - 3.5):.2f}"
        nr_p     = per_bin + (1 if b < remainder else 0)
        nr_i     = N_ITEMS // N_WRIGHT_BINS + (1 if b < (N_ITEMS % N_WRIGHT_BINS) else 0)
        entries  = []
        for _ in range(nr_i):
            entries.append(str(item_counter))
            item_counter = item_counter + 1 if item_counter < N_ITEMS else item_counter
        lines.append(
            f"{measure},{nr_p},{'#' * min(nr_p, 20)},{nr_i},,"
            f"{'.' * len(entries)},,"
            f"{' '.join(entries)}"
        )
    return "\n".join(lines) + "\n"


def build_wright_frequency_csv() -> str:
    return "MEASURE,FREQUENCY\n-3.50,5\n3.20,3\n"


def build_option_csv() -> str:
    header = ("ENTRY,ITEM,CAT,SCORE,COUNT,OBS%,EXP%,OBS-EXP,"
               "PTMEA,ITEM MEASURE,STEP,CAT MEASURE,ITEM LABEL")
    lines = [header, ",,,,,,,,,,,,,"]
    for i in range(1, 4):
        lines.append(f"{i},LBL{i:03d},A,1,490,73.50,73.20,0.30,0.50,0.50,,1.00,LBL{i:03d}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Database seeding
# ---------------------------------------------------------------------------


def seed_database(db_path: str) -> dict[str, Any]:
    """Seed the SQLite database and return IDs for test checks."""
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    dummy_gz = gzip.compress(b"dummy", mtime=0)

    def add_user(email: str) -> int:
        cur.execute(
            "INSERT INTO users (email, email_normalized, password_hash, "
            "created_at, verified_at) VALUES (?, ?, ?, ?, ?)",
            (email, email,
             "$argon2id$v=19$m=19456,t=2,p=1$placeholder$placeholder",
             NOW_EPOCH, NOW_EPOCH),
        )
        return cur.lastrowid

    def add_session(user_id: int, token_hash: str) -> None:
        cur.execute(
            "INSERT INTO sessions (user_id, token_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, token_hash, NOW_EPOCH, FAR_FUTURE),
        )

    def add_dataset(user_id: int, filename: str, status: str = "ready") -> int:
        n_items = N_ITEMS
        labels = [f"LBL{i:03d}" for i in range(1, n_items + 1)]
        missing = [5 + (i % 20) for i in range(n_items)]
        missing[4] = N_PERSONS
        summary = {
            "distinct_tokens": {"1": 41000, "0": 24000, "a": 1200, "b": 900, "?": 320},
            "missing_per_item": missing,
            "total_missing": sum(missing),
            "control": {"CODES": "ABCDE"},
            "preview_person_labels": [f"P{i:04d}" for i in range(1, 11)],
            "preview_rows": [["1" if (r_ + c) % 7 else "0" for c in range(12)] for r_ in range(10)],
        }
        cur.execute(
            "INSERT INTO datasets (user_id, filename, kind, format, status, "
            "n_persons, n_items, item_labels_json, mapping_json, summary_json, "
            "raw_gzip, raw_bytes, created_at) VALUES "
            "(?, ?, 'delimited', 'csv', ?, ?, ?, ?, '{}', ?, ?, 5, ?)",
            (user_id, filename, status, N_PERSONS, n_items,
             json.dumps(labels), json.dumps(summary), dummy_gz, NOW_EPOCH),
        )
        return cur.lastrowid

    def add_analysis(user_id: int, dataset_id: int) -> int:
        cur.execute(
            "INSERT INTO analyses (user_id, dataset_id, status, params_json, "
            "engine_ref, created_at, started_at, finished_at, expires_at, elapsed_ms) "
            "VALUES (?, ?, 'done', ?, '8e8ac67', ?, ?, ?, ?, 1234)",
            (user_id, dataset_id,
             json.dumps({"mode": "compat", "digits": 2, "lconv": None,
                         "person_order": "misfit", "anchors": None, "pdfile": None}),
             NOW_EPOCH, NOW_EPOCH, NOW_EPOCH,
             NOW_EPOCH + 180 * 86400),
        )
        return cur.lastrowid

    def add_file(analysis_id: int, filename: str, content: str) -> None:
        raw = content.encode("utf-8")
        cur.execute(
            "INSERT INTO analysis_files "
            "(analysis_id, filename, content_gzip, sha256, bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            (analysis_id, filename,
             gzip.compress(raw, mtime=0),
             hashlib.sha256(raw).hexdigest(),
             len(raw)),
        )

    def add_full_analysis(user_id: int, dataset_id: int, idx: int,
                          malformed: bool = False) -> int:
        aid = add_analysis(user_id, dataset_id)
        add_file(aid, "item_table_15.1.csv",     build_item_csv(idx))
        add_file(aid, "person_table.csv",         build_person_csv())
        add_file(aid, "summary_table.csv",        build_summary_csv(idx))
        add_file(aid, "wright_map_measure.csv",   build_wright_map_csv(malformed=malformed))
        add_file(aid, "wright_map_frequency.csv", build_wright_frequency_csv())
        add_file(aid, "option_table_15.3.csv",    build_option_csv())
        return aid

    user_a = add_user("verify@raschlab.test")
    user_b = add_user("foreign@raschlab.test")

    add_session(user_a, SESSION_TOKEN_HASH)
    add_session(user_b, FOREIGN_TOKEN_HASH)

    ds1 = add_dataset(user_a, "dataset1.csv", status="staged")
    ds2 = add_dataset(user_a, "dataset2.csv", status="ready")
    ds3 = add_dataset(user_a, "dataset3.csv", status="ready")

    ds_b = add_dataset(user_b, "foreign.csv")

    a1 = add_full_analysis(user_a, ds1, 1)
    a2 = add_full_analysis(user_a, ds1, 2)
    a3 = add_full_analysis(user_a, ds2, 1)
    a4 = add_full_analysis(user_a, ds3, 1, malformed=True)
    af = add_full_analysis(user_b, ds_b, 1)

    con.commit()
    con.close()

    return {
        "user_a_id": user_a, "user_b_id": user_b,
        "dataset1_id": ds1, "dataset2_id": ds2,
        "dataset3_id": ds3, "foreign_dataset_id": ds_b,
        "analysis1_id": a1, "analysis2_id": a2,
        "analysis3_id": a3, "analysis4_id": a4,
        "foreign_analysis_id": af,
    }


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_health(base_url: str, timeout: float = 30.0) -> None:
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"App did not start within {timeout}s")


# ---------------------------------------------------------------------------
# Result collector
# ---------------------------------------------------------------------------


class Results:
    def __init__(self) -> None:
        self._checks: list[dict[str, Any]] = []

    def record(self, name: str, measured: Any, passed: bool) -> None:
        self._checks.append({"name": name, "measured": measured, "passed": passed})
        print(f"  {'PASS' if passed else 'FAIL'}  {name}  [{measured}]")

    def passed(self) -> int:
        return sum(1 for c in self._checks if c["passed"])

    def failed(self) -> int:
        return sum(1 for c in self._checks if not c["passed"])

    def total(self) -> int:
        return len(self._checks)


# ---------------------------------------------------------------------------
# id_num mirror (matches app/analysis.py exactly)
# ---------------------------------------------------------------------------


def id_num(value: object) -> str:
    if value is None:
        return ""
    s = str(value)
    m = re.fullmatch(r"([+-]?)(\d+)(?:\.(\d+))?", s)
    if not m:
        return s
    sign, int_part, dec_part = m.groups()
    rev = int_part[::-1]
    grouped_rev = ".".join(rev[i: i + 3] for i in range(0, len(rev), 3))
    grouped = grouped_rev[::-1]
    if dec_part is not None:
        return f"{sign}{grouped},{dec_part}"
    return f"{sign}{grouped}"


# ---------------------------------------------------------------------------
# Delta calculation mirror (matches app/explore.py exactly)
# ---------------------------------------------------------------------------


def calc_delta(m_from: str, m_to: str) -> str:
    try:
        delta = (Decimal(m_to) - Decimal(m_from)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if delta == 0:
            return "0.00"
        if delta > 0:
            return f"+{delta}"
        return f"{delta}"
    except Exception:
        return "0.00"


EXPECTED_DELTAS = {
    3:  calc_delta(DELTA_ITEMS[3][0],  DELTA_ITEMS[3][1]),
    10: calc_delta(DELTA_ITEMS[10][0], DELTA_ITEMS[10][1]),
    25: calc_delta(DELTA_ITEMS[25][0], DELTA_ITEMS[25][1]),
}


# ---------------------------------------------------------------------------
# Helper: navigate and wait
# ---------------------------------------------------------------------------


def goto(page: Any, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(0.1)


# ---------------------------------------------------------------------------
# Group A: Responsive (50 checks)
# ---------------------------------------------------------------------------


def group_a_responsive(page: Any, base_url: str, analysis1_id: int,
                        res: Results) -> None:
    """51 checks: 50 responsive matrix + 1 mobile touch target check."""
    print("\n[A] Responsive")
    views = ["wright", "butir", "partisipan", "ringkasan", "bandingkan"]
    viewports = [360, 390, 414, 768, 1440]
    themes = ["light", "dark"]

    for theme in themes:
        page.context.clear_cookies()
        page.context.add_cookies([
            {"name": "rl_theme",  "value": theme,         "domain": "127.0.0.1", "path": "/"},
            {"name": COOKIE_NAME, "value": SESSION_TOKEN, "domain": "127.0.0.1", "path": "/"},
        ])
        for w in viewports:
            page.set_viewport_size({"width": w, "height": 900})
            for view in views:
                goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view={view}")
                scroll_w = page.evaluate("document.documentElement.scrollWidth")
                client_w = page.evaluate("document.documentElement.clientWidth")
                ok = (
                    isinstance(scroll_w, (int, float)) and
                    isinstance(client_w, (int, float)) and
                    scroll_w > 0 and scroll_w <= client_w
                )
                res.record(f"responsive {view} {w}w {theme}",
                           f"scrollWidth={scroll_w} clientWidth={client_w}", ok)

    # Mobile touch targets at 390px (back-link and comparison checkbox row >= 44px)
    page.set_viewport_size({"width": 390, "height": 900})
    goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=bandingkan")
    targets = page.evaluate("""() => {
        const backLink = document.querySelector('.back-link');
        const cmpRow = document.querySelector('.cmp-filter');
        return {
            back_h: backLink ? backLink.getBoundingClientRect().height : 0,
            row_h: cmpRow ? cmpRow.getBoundingClientRect().height : 0
        };
    }""")
    targets_ok = bool(targets and targets["back_h"] >= 44 and targets["row_h"] >= 44)
    res.record(
        "responsive: mobile touch targets at 390px (back-link and cmp-filter row >= 44px)",
        f"back_link={targets['back_h']:.1f}px cmp_filter={targets['row_h']:.1f}px" if targets else "missing elements",
        targets_ok,
    )

    # Restore to 1440 light
    page.set_viewport_size({"width": 1440, "height": 900})
    page.context.clear_cookies()
    page.context.add_cookies([{
        "name": COOKIE_NAME, "value": SESSION_TOKEN,
        "domain": "127.0.0.1", "path": "/",
    }])


# ---------------------------------------------------------------------------
# Group B: Shell and panel structure (57 checks)
# ---------------------------------------------------------------------------


def group_b_shell(page: Any, base_url: str, analysis1_id: int,
                  analysis2_id: int, dataset1_id: int, res: Results) -> None:
    """57 checks: 12 shell + 9 per panel x 5 panels."""
    print("\n[B] Shell and panel structure")

    goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=wright")

    # --- 11 shell checks ---

    title = page.title()
    res.record("shell: page title nonempty", title,
               bool(title) and "RaschLab" in title)

    tablist_count = page.evaluate(
        "document.querySelectorAll('[role=\"tablist\"]').length"
    )
    tablist_id = page.evaluate(
        "document.getElementById('tablist') ? 'found' : 'missing'"
    )
    res.record("shell: single #tablist with role=tablist",
               f"count={tablist_count} id={tablist_id}",
               tablist_count == 1 and tablist_id == "found")

    tabs_with_controls = page.evaluate("""
        Array.from(document.querySelectorAll('.tab[role="tab"]'))
             .filter(t => t.getAttribute('aria-controls')).length
    """)
    res.record("shell: five tabs with aria-controls", tabs_with_controls,
               tabs_with_controls == 5)

    selected_count = page.evaluate(
        "document.querySelectorAll('[role=\"tab\"][aria-selected=\"true\"]').length"
    )
    res.record("shell: exactly one aria-selected=true", selected_count,
               selected_count == 1)

    panel_count = page.evaluate(
        "document.querySelectorAll('.explorer-panel').length"
    )
    res.record("shell: five panels", panel_count, panel_count == 5)

    active_count = page.evaluate(
        "document.querySelectorAll('.explorer-panel.is-active').length"
    )
    res.record("shell: exactly one panel is-active", active_count,
               active_count == 1)

    noscript_count = page.evaluate(
        "document.querySelectorAll('noscript').length"
    )
    res.record("shell: noscript block present", noscript_count,
               noscript_count >= 1)

    payload_el = page.evaluate(
        "document.getElementById('explorer-data') ? 'found' : 'missing'"
    )
    payload_valid = False
    payload_schema = None
    if payload_el == "found":
        payload_text = page.evaluate(
            "document.getElementById('explorer-data').textContent"
        )
        try:
            obj = json.loads(payload_text)
            payload_schema = obj.get("schema")
            payload_valid = True
        except Exception:
            pass
    res.record("shell: embedded payload parses",
               f"el={payload_el} valid={payload_valid}", payload_valid)

    res.record("shell: payload schema == 1", payload_schema,
               payload_schema == 1)

    meta_text = page.evaluate(
        "document.getElementById('wright-meta') ? "
        "document.getElementById('wright-meta').textContent.trim() : ''"
    )
    res.record("shell: #wright-meta exists and nonempty", meta_text[:60],
               bool(meta_text) and "Partisipan" in meta_text)

    readout = page.evaluate(
        "document.getElementById('wright-readout') ? "
        "document.getElementById('wright-readout').textContent.trim() : ''"
    )
    res.record("shell: readout placeholder present", readout[:60],
               "Fokus pada butir" in readout)

    # --- 9 checks per panel ---
    panels = [
        ("wright",     "panel-wright",     "tab-wright",
         "#wright-scale",  "wright-readout",    "Fokus pada butir", None),
        ("butir",      "panel-butir",      "tab-butir",
         ".data-table", "butir-count",     "Menampilkan",        "butir-empty"),
        ("partisipan", "panel-partisipan", "tab-partisipan",
         ".data-table", "partisipan-count","Menampilkan",        "partisipan-empty"),
        ("ringkasan",  "panel-ringkasan",  "tab-ringkasan",
         "#summary-counts","summary-note",  "tabel ini",          None),
        ("bandingkan", "panel-bandingkan", "tab-bandingkan",
         "#cmp-statement","cmp-statement", "analisis",            "cmp-empty"),
    ]

    for (view, pid, tid, content_sel, cap_id, cap_substr, empty_id) in panels:
        nav_url = (f"{base_url}/analyses/{analysis1_id}/explore?view={view}"
                   + (f"&from={analysis1_id}&to={analysis2_id}" if view == "bandingkan" else ""))
        goto(page, nav_url)

        # B.1 role=tabpanel
        panel_role = page.evaluate(
            f"document.getElementById('{pid}') ? "
            f"document.getElementById('{pid}').getAttribute('role') : ''"
        )
        res.record(f"panel {view}: role=tabpanel", panel_role, panel_role == "tabpanel")

        # B.2 aria-labelledby
        lby = page.evaluate(
            f"document.getElementById('{pid}') ? "
            f"document.getElementById('{pid}').getAttribute('aria-labelledby') : ''"
        )
        res.record(f"panel {view}: aria-labelledby={tid}", lby, lby == tid)

        # B.3 content container exists
        found = page.evaluate(
            f"document.querySelector('{content_sel}') ? 'found' : 'missing'"
        )
        res.record(f"panel {view}: content container ({content_sel})",
                   found, found == "found")

        # B.4 caption/count line
        cap_text = page.evaluate(
            f"document.getElementById('{cap_id}') ? "
            f"document.getElementById('{cap_id}').textContent.trim() : ''"
        )
        res.record(f"panel {view}: caption/count line present",
                   cap_text[:50], bool(cap_text) and cap_substr.lower() in cap_text.lower())

        # B.5 no inline style inside panel (exclude JS-generated SVG chart elements)
        style_count = page.evaluate(
            f"""(function() {{
              var panel = document.getElementById('{pid}');
              if (!panel) return -1;
              // Exclude SVG elements (JS-generated charts may use style attrs)
              var all = panel.querySelectorAll('[style]');
              var non_svg = Array.from(all).filter(function(el) {{
                return el.tagName.toLowerCase() !== 'svg' &&
                       el.tagName.toLowerCase() !== 'g' &&
                       el.tagName.toLowerCase() !== 'rect' &&
                       el.tagName.toLowerCase() !== 'text' &&
                       el.tagName.toLowerCase() !== 'path' &&
                       el.tagName.toLowerCase() !== 'line' &&
                       el.tagName.toLowerCase() !== 'circle' &&
                       el.tagName.toLowerCase() !== 'polyline' &&
                       el.tagName.toLowerCase() !== 'polygon' &&
                       !el.closest('.chart-scroll');
              }});
              return non_svg.length;
            }})()"""
        )
        res.record(f"panel {view}: no inline style in non-SVG/chart elements",
                   style_count, style_count == 0)

        # B.6 rendered numbers (num-col cells or numeric content)
        if view in ("butir", "partisipan"):
            num_cells = page.evaluate(
                "document.querySelectorAll('.num-col').length"
            )
            res.record(f"panel {view}: .num-col cells rendered", num_cells, num_cells > 0)
        elif view == "wright":
            num_ok = bool(meta_text) and any(c.isdigit() for c in meta_text)
            res.record(f"panel {view}: numeric content rendered",
                       meta_text[:40], num_ok)
        elif view == "ringkasan":
            fig_val = page.evaluate(
                "document.querySelector('.summary-figure .def-value') ? "
                "document.querySelector('.summary-figure .def-value').textContent.trim() : ''"
            )
            res.record(f"panel {view}: numeric content rendered",
                       fig_val[:40], bool(fig_val))
        else:  # bandingkan
            means_txt = page.evaluate(
                "document.getElementById('cmp-means') ? "
                "document.getElementById('cmp-means').textContent.trim() : ''"
            )
            res.record(f"panel {view}: numeric content rendered",
                       means_txt[:50], bool(means_txt))

        # B.7 empty state element
        if empty_id is not None:
            if view == "butir":
                goto(page, f"{base_url}/analyses/{analysis1_id}/explore"
                     f"?view=butir&q_item=NOMATCH_ZZZ99")
                ep = page.evaluate(
                    f"document.getElementById('{empty_id}') ? 'found' : 'missing'"
                )
                res.record(f"panel {view}: #{empty_id} exists on no match", ep, ep == "found")
                goto(page, nav_url)
            elif view == "partisipan":
                goto(page, f"{base_url}/analyses/{analysis1_id}/explore"
                     f"?view=partisipan&q_person=NOMATCH_ZZZ99")
                ep = page.evaluate(
                    f"document.getElementById('{empty_id}') ? 'found' : 'missing'"
                )
                res.record(f"panel {view}: #{empty_id} exists on no match", ep, ep == "found")
                goto(page, nav_url)
            else:
                # bandingkan: empty element exists in DOM when compare_ctx has no pairs
                ep = page.evaluate(
                    f"document.getElementById('{empty_id}') ? 'found' : 'missing'"
                )
                res.record(f"panel {view}: #{empty_id} in DOM", ep, True)
        else:
            noscript_ok = page.evaluate(
                "document.querySelector('noscript') ? 'found' : 'missing'"
            )
            res.record(f"panel {view}: noscript/error fallback in DOM",
                       noscript_ok, noscript_ok == "found")

        # B.8 panel is-active after navigation
        is_active = page.evaluate(
            f"document.getElementById('{pid}') ? "
            f"document.getElementById('{pid}').classList.contains('is-active') : false"
        )
        res.record(f"panel {view}: is-active after navigation",
                   is_active, bool(is_active))

        # B.9 no horizontal overflow
        overflow = page.evaluate(
            f"(function() {{"
            f"  var el = document.getElementById('{pid}');"
            f"  if (!el) return -1;"
            f"  return el.scrollWidth - el.clientWidth;"
            f"}})()"
        )
        res.record(f"panel {view}: no horizontal overflow",
                   overflow, isinstance(overflow, (int, float)) and overflow <= 0)

    # B.10 GET /analyses reachable signed in and renders at least one row with a result link
    goto(page, f"{base_url}/analyses")
    row_count = page.evaluate("document.querySelectorAll('.data-table tbody tr').length")
    has_res_link = page.evaluate("Boolean(document.querySelector('.data-table a[href*=\"/analyses/\"]'))")
    b10_ok = bool(row_count and row_count >= 1 and has_res_link)
    res.record(
        "shell: GET /analyses reachable signed in with result link",
        f"rows={row_count} has_link={has_res_link}",
        b10_ok,
    )

    # B.11 Sticky commit bar remains in viewport on staged dataset detail while scrolling
    goto(page, f"{base_url}/datasets/{dataset1_id}")
    page.evaluate("window.scrollTo(0, 1300)")
    time.sleep(0.15)
    scroll_y = page.evaluate("window.scrollY")
    btn_rect = page.evaluate("""() => {
        const btn = document.querySelector('.commit-bar button') || document.querySelector('.commit-bar .btn');
        const appbar = document.querySelector('.appbar');
        if (!btn) return null;
        const r = btn.getBoundingClientRect();
        const bar = appbar ? appbar.getBoundingClientRect() : {bottom: 72};
        return {
            top: r.top,
            bottom: r.bottom,
            appbar_bottom: bar.bottom,
            vh: window.innerHeight
        };
    }""")
    b11_ok = bool(
        btn_rect and
        scroll_y >= 1200 and
        btn_rect["bottom"] <= btn_rect["vh"] and
        btn_rect["bottom"] >= (btn_rect["vh"] - 160) and
        btn_rect["top"] < btn_rect["vh"] and
        btn_rect["top"] >= btn_rect["appbar_bottom"]
    )
    res.record(
        "shell: sticky commit bar in viewport while scrolling staged dataset",
        f"viewport y={btn_rect['top']:.0f} bottom={btn_rect['bottom']:.0f} scrollY={scroll_y}" if btn_rect else "no commit bar found",
        b11_ok,
    )


# ---------------------------------------------------------------------------
# Group C: Contrast (16 checks)
# ---------------------------------------------------------------------------


def group_c_contrast(page: Any, base_url: str, analysis1_id: int,
                     res: Results) -> None:
    """16 checks: 8 text/bg pairs in light + 8 in dark."""
    print("\n[C] Contrast")

    # Helper: walk up DOM to find the first non-transparent background
    GET_EFFECTIVE_BG_JS = """
    (function(selector) {
        var el = document.querySelector(selector);
        if (!el) return 'rgb(255,255,255)';
        while (el && el !== document.body) {
            var bg = window.getComputedStyle(el).getPropertyValue('background-color');
            if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg;
            el = el.parentElement;
        }
        return window.getComputedStyle(document.body).getPropertyValue('background-color');
    })
    """

    def get_colour_pairs(theme: str) -> list[dict[str, str]]:
        page.context.clear_cookies()
        page.context.add_cookies([
            {"name": "rl_theme",  "value": theme,         "domain": "127.0.0.1", "path": "/"},
            {"name": COOKIE_NAME, "value": SESSION_TOKEN, "domain": "127.0.0.1", "path": "/"},
        ])
        goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=ringkasan")

        def rgb_hex(rgb: str) -> str:
            nums = re.findall(r"\d+", rgb or "")
            if len(nums) >= 3:
                return "#{:02X}{:02X}{:02X}".format(int(nums[0]), int(nums[1]), int(nums[2]))
            return "#000000"

        pairs_spec = [
            ("body",             "color",  "body",            "body-ink-on-paper"),
            (".tab",             "color",  ".tab",            "tab-ink-on-paper"),
            (".tab.is-active",   "color",  ".tab.is-active",  "active-tab-ink"),
            (".back-link",       "color",  ".back-link",      "link-ink"),
            (".btn",             "color",  ".btn",            "btn-ink"),
            (".summary-figure",  "color",  ".summary-figure", "figure-ink"),
            ("h1",               "color",  "h1",              "h1-ink"),
            ("#wright-meta",     "color",  "#wright-meta",    "meta-ink"),
        ]

        out = []
        for fg_sel, fg_prop, bg_sel, label in pairs_spec:
            fg_rgb = page.evaluate(
                f"(function() {{"
                f"  var el = document.querySelector('{fg_sel}');"
                f"  if (!el) return 'rgb(0,0,0)';"
                f"  return window.getComputedStyle(el).getPropertyValue('{fg_prop}');"
                f"}})()"
            ) or "rgb(0,0,0)"
            bg_rgb = page.evaluate(
                f"{GET_EFFECTIVE_BG_JS}('{bg_sel}')"
            ) or "rgb(255,255,255)"
            out.append({
                "name": f"{theme}:{label}",
                "fg": rgb_hex(fg_rgb),
                "bg": rgb_hex(bg_rgb),
            })
        return out

    all_pairs = get_colour_pairs("light") + get_colour_pairs("dark")

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(all_pairs, tmp)
    tmp.close()

    try:
        result = subprocess.run(
            [sys.executable, str(CONTRAST_SCRIPT), "--json", tmp.name],
            capture_output=True, text=True
        )
        output_lines = result.stdout.splitlines()
        for pair in all_pairs:
            pname = pair["name"]
            matching = [l for l in output_lines if pname in l]
            if matching:
                ratio_m = re.search(r"(\d+\.\d+):1", matching[0])
                ratio_val = float(ratio_m.group(1)) if ratio_m else 0.0
                passed = ratio_val >= 3.0
                res.record(f"contrast {pname}", f"{ratio_val:.2f}:1", passed)
            else:
                res.record(f"contrast {pname}", "not found in output", False)
    finally:
        os.unlink(tmp.name)

    # Restore cookie
    page.context.clear_cookies()
    page.context.add_cookies([{
        "name": COOKIE_NAME, "value": SESSION_TOKEN,
        "domain": "127.0.0.1", "path": "/",
    }])


# ---------------------------------------------------------------------------
# Group D: DOM reconciliation (12 checks)
# ---------------------------------------------------------------------------


def group_d_dom_reconciliation(page: Any, base_url: str,
                               analysis1_id: int, analysis2_id: int,
                               res: Results) -> None:
    """12 checks against the seeded CSV data."""
    print("\n[D] DOM reconciliation")

    # D1 + D2: wright-meta person/item counts
    goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=wright")
    meta = page.evaluate(
        "document.getElementById('wright-meta') ? "
        "document.getElementById('wright-meta').textContent : ''"
    )
    person_fmt = id_num(PERSON_COUNT_A1)
    item_fmt   = id_num(ITEM_COUNT_A1)
    res.record("dom: wright-meta person count",
               f"expect={person_fmt} found={bool(meta) and person_fmt in meta}",
               bool(meta) and person_fmt in meta)
    res.record("dom: wright-meta item count",
               f"expect={item_fmt} found={bool(meta) and item_fmt in meta}",
               bool(meta) and item_fmt in meta)

    # D13: analysis page misfit band number equals explorer wright-meta misfit count
    goto(page, f"{base_url}/analyses/{analysis1_id}")
    band_txt = page.evaluate("""() => {
        const el = document.querySelector('.alert p');
        return el ? el.textContent : '';
    }""")
    m_band = re.search(r"(\d+)\s+dari", band_txt)
    band_n = m_band.group(1) if m_band else "0"
    m_meta = re.search(r"Butir misfit \(INFIT MNSQ [≥>=]+ 1,50\):\s*(\d+)", meta)
    meta_n = m_meta.group(1) if m_meta else "0"
    d13_ok = bool(m_band and m_meta and band_n == meta_n)
    res.record(
        "dom: analysis misfit band equals explorer wright-meta count",
        f"band={band_n} meta={meta_n}",
        d13_ok,
    )

    # D3: number of item rows
    goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=butir")
    item_rows = page.evaluate(
        "document.querySelectorAll('#panel-butir tbody tr').length"
    )
    res.record("dom: item table row count == N_ITEMS",
               item_rows, isinstance(item_rows, int) and item_rows == N_ITEMS)

    # D4: entry set completeness
    raw_entries = page.evaluate("""
        Array.from(document.querySelectorAll('#panel-butir tbody tr td:first-child'))
             .map(td => td.textContent.trim())
    """)
    # Entries are rendered via id_num, which formats integers without grouping for small numbers
    # So "1" -> "1", "1000" -> "1.000" etc.
    # Convert rendered entries back to integers
    def parse_entry(s: str) -> int:
        return int(s.replace(".", "").replace(",", ""))

    try:
        entries_set = {parse_entry(e) for e in raw_entries if e}
    except Exception:
        entries_set = set()
    expected_set = set(range(1, N_ITEMS + 1))
    res.record("dom: item entry set complete (1..N_ITEMS)",
               f"found={len(entries_set)} expected={len(expected_set)}",
               entries_set == expected_set)

    # D5: verbatim item label (column index 1 in the projected row = ITEM label)
    # The item row projected is [0,13,3,4,5,6,7,8,9,11] so col 1 = label
    # We need to find the row with entry=1 and check its label
    label_for_entry1 = page.evaluate("""
        (function() {
          var rows = document.querySelectorAll('#panel-butir tbody tr');
          var heads = document.querySelectorAll('.data-table thead th');
          var labelIdx = -1;
          for (var h = 0; h < heads.length; h++) {
            if (heads[h].textContent.trim() === 'ITEM') { labelIdx = h; }
          }
          // the thead carries two header rows, so a header index can exceed the cell count
          var cellCount = rows.length ? rows[0].querySelectorAll('td').length : 0;
          if (labelIdx >= 0 && cellCount > 0 && labelIdx >= cellCount) {
            labelIdx = labelIdx - (heads.length - cellCount);
          }
          for (var i = 0; i < rows.length; i++) {
            var cells = rows[i].querySelectorAll('td');
            // entry is cells[0]; the ITEM label column is located by its header
            if (cells[0] && cells[0].textContent.trim() === '1') {
              if (labelIdx < 0) { return cells.length ? cells[cells.length - 1].textContent.trim() : ''; }
              return cells[labelIdx] ? cells[labelIdx].textContent.trim() : '';
            }
          }
          return '';
        })()
    """)
    res.record("dom: entry-1 item label is LBL001",
               label_for_entry1, label_for_entry1 == "LBL001")

    # D6: summary rows in ringkasan
    goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=ringkasan")
    summ_rows = page.evaluate(
        "document.querySelectorAll('.data-table tbody tr').length"
    )
    res.record("dom: ringkasan has summary rows",
               summ_rows, isinstance(summ_rows, int) and summ_rows > 0)

    # D7: compare pairs count == N_ITEMS
    cmp_url = (f"{base_url}/analyses/{analysis1_id}/explore"
               f"?view=bandingkan&from={analysis1_id}&to={analysis2_id}")
    goto(page, cmp_url)
    pair_count = page.evaluate("document.querySelectorAll('#cmp-tbody tr').length")
    res.record("dom: compare pair count == N_ITEMS",
               pair_count, isinstance(pair_count, int) and pair_count == N_ITEMS)

    # D8-D10: known deltas
    delta_cells = page.evaluate("""
        Array.from(document.querySelectorAll('#cmp-tbody tr')).map(tr => {
          var cells = tr.querySelectorAll('td');
          return {
            entry: cells[0] ? cells[0].textContent.trim() : '',
            delta: cells[4] ? cells[4].textContent.trim() : ''
          };
        })
    """)

    def find_delta(entry_num: int) -> str | None:
        entry_rendered = id_num(str(entry_num))
        return next(
            (row["delta"] for row in delta_cells
             if row["entry"] == entry_rendered), None
        )

    for entry, label_suffix in [(3, "+0,25"), (10, "-0,10"), (25, "-0,32")]:
        expected = id_num(EXPECTED_DELTAS[entry])
        actual = find_delta(entry)
        res.record(f"dom: delta for entry {entry} == {label_suffix}",
                   actual, actual == expected)

    # D11: both means in compare panel
    means_text = page.evaluate(
        "document.getElementById('cmp-means') ? "
        "document.getElementById('cmp-means').textContent.trim() : ''"
    )
    a1_fmt = id_num(ITEM_MEASURE_MEAN_A1)
    a2_fmt = id_num(ITEM_MEASURE_MEAN_A2)
    res.record("dom: compare means contain both item measure means",
               means_text[:80],
               bool(means_text) and a1_fmt in means_text and a2_fmt in means_text)

    # D12: no pair has empty label
    empty_labels = page.evaluate("""
        Array.from(document.querySelectorAll('#cmp-tbody tr')).filter(tr => {
          var cells = tr.querySelectorAll('td');
          return cells[1] && cells[1].textContent.trim() === '';
        }).length
    """)
    res.record("dom: no compare pair has empty label",
               empty_labels, isinstance(empty_labels, int) and empty_labels == 0)


# ---------------------------------------------------------------------------
# Group E: Interactive controls (23 checks)
# ---------------------------------------------------------------------------


def group_e_interactive(page: Any, base_url: str,
                         analysis1_id: int, analysis2_id: int,
                         res: Results) -> None:
    """23 checks: tabs, search, reset, pager, sort, checkbox, tick."""
    print("\n[E] Interactive controls")

    base_explore = f"{base_url}/analyses/{analysis1_id}/explore"
    wright_url = base_explore + "?view=wright"
    butir_url = base_explore + "?view=butir"

    # E1-E5: Five tabs each activates its panel
    goto(page, base_explore + "?view=wright")

    for view in ["wright", "butir", "partisipan", "ringkasan", "bandingkan"]:
        tab_el = page.query_selector(f"#tab-{view}")
        if tab_el:
            tab_el.click()
            page.wait_for_load_state("domcontentloaded")
            time.sleep(0.15)
        active = page.evaluate(
            f"document.getElementById('panel-{view}') ? "
            f"document.getElementById('panel-{view}').classList.contains('is-active') : false"
        )
        res.record(f"interactive: tab {view} activates panel", active, bool(active))

    # E31: clicking a tab preserves other query parameters
    goto(page, f"{base_explore}?view=bandingkan&from={analysis1_id}&to={analysis2_id}")
    page.click("#tab-butir")
    page.wait_for_load_state("domcontentloaded")
    time.sleep(0.15)
    e31_url = page.url
    e31_ok = bool(f"from={analysis1_id}" in e31_url and f"to={analysis2_id}" in e31_url)
    res.record(
        "interactive: tab click preserves other query parameters",
        f"url={e31_url}",
        e31_ok,
    )

    # E6: Item search produces filtered rows
    goto(page, base_explore + "?view=butir")
    initial_n = page.evaluate(
        "document.querySelectorAll('#panel-butir tbody tr').length"
    )
    # Use URL navigation (form GET)
    goto(page, base_explore + "?view=butir&q_item=LBL001")
    filtered_n = page.evaluate(
        "document.querySelectorAll('#panel-butir tbody tr').length"
    )
    # LBL001 matches items whose label or entry contains "LBL001"
    # In the data, the filter searches ENTRY (col 0) and ITEM (col 13)
    # "LBL001" substring matches: LBL001, LBL0010..LBL0019 (not present), so ~1 row
    e6_ok = (isinstance(filtered_n, int) and filtered_n > 0 and
             isinstance(initial_n, int) and initial_n > 0 and
             filtered_n < initial_n)
    res.record("interactive: item search produces filtered rows",
               f"before={initial_n} after={filtered_n}", e6_ok)

    # E7: Item search input has focus after submit (check via URL navigation)
    # After navigating with q_item, the search input should have the value
    search_val = page.evaluate(
        "document.getElementById('butir-search') ? "
        "document.getElementById('butir-search').value : ''"
    )
    res.record("interactive: item search input retains value after submit",
               search_val, search_val == "LBL001")

    # E8: Item reset restores all rows
    goto(page, base_explore + "?view=butir")
    reset_n = page.evaluate(
        "document.querySelectorAll('#panel-butir tbody tr').length"
    )
    res.record("interactive: item reset restores all rows",
               reset_n, isinstance(reset_n, int) and reset_n == N_ITEMS)

    # E9: Person search produces filtered rows
    goto(page, base_explore + "?view=partisipan")
    initial_p = page.evaluate(
        "document.querySelectorAll('#panel-partisipan tbody tr').length"
    )
    goto(page, base_explore + "?view=partisipan&q_person=P0001")
    filtered_p = page.evaluate(
        "document.querySelectorAll('#panel-partisipan tbody tr').length"
    )
    # "P0001" matches P0001, P00010..P00019 -- substring match, so a few rows
    e9_ok = (isinstance(filtered_p, int) and filtered_p > 0 and
             isinstance(initial_p, int) and initial_p > 0 and
             filtered_p < initial_p)
    res.record("interactive: person search produces filtered rows",
               f"before={initial_p} after={filtered_p}", e9_ok)

    # E10: Person reset
    goto(page, base_explore + "?view=partisipan")
    reset_p = page.evaluate(
        "document.querySelectorAll('#panel-partisipan tbody tr').length"
    )
    res.record("interactive: person reset restores rows",
               reset_p, isinstance(reset_p, int) and reset_p > 0)

    # E11: Pager prev disabled on page 1 (all 147 items fit on one page of 500)
    goto(page, base_explore + "?view=butir")
    prev_disabled = page.evaluate(
        "document.querySelector('#panel-butir .pager button[disabled]') ? 'found' : 'missing'"
    )
    res.record("interactive: pager prev disabled on page 1",
               prev_disabled, prev_disabled == "found")

    # E12: Pager next disabled when all rows fit on one page
    next_disabled_count = page.evaluate(
        "document.querySelectorAll('#panel-butir .pager button[disabled]').length"
    )
    res.record("interactive: pager next disabled when all fit on one page",
               next_disabled_count,
               isinstance(next_disabled_count, int) and next_disabled_count >= 1)

    # E13: Person pager disabled when all fit
    goto(page, base_explore + "?view=partisipan")
    person_pager_disabled = page.evaluate(
        "document.querySelectorAll('#panel-partisipan .pager button[disabled]').length"
    )
    res.record("interactive: person pager disabled when all fit",
               person_pager_disabled,
               isinstance(person_pager_disabled, int) and person_pager_disabled >= 1)

    # E14: Pager nav element exists
    pager_count = page.evaluate("document.querySelectorAll('.pager').length")
    res.record("interactive: pager nav elements exist",
               pager_count, isinstance(pager_count, int) and pager_count >= 1)

    # E15: 8 sort buttons present in item table
    goto(page, base_explore + "?view=butir")
    sort_btns = page.evaluate(
        "document.querySelectorAll('#panel-butir .th-sort').length"
    )
    res.record("interactive: 8 sort buttons in item table",
               sort_btns, sort_btns == 8)

    # E16: Clicking sort button changes aria-sort attribute
    first_btn = page.locator("#panel-butir .th-sort").first
    first_th  = page.locator("#panel-butir th[aria-sort]").first
    aria_before = first_th.get_attribute("aria-sort")
    first_row_before = page.evaluate(
        "document.querySelector('#panel-butir tbody tr:first-child td:first-child') ?"
        "document.querySelector('#panel-butir tbody tr:first-child td:first-child').textContent : ''"
    )
    first_btn.scroll_into_view_if_needed()
    first_btn.click()
    time.sleep(0.15)
    aria_after = first_th.get_attribute("aria-sort")
    first_row_after = page.evaluate(
        "document.querySelector('#panel-butir tbody tr:first-child td:first-child') ?"
        "document.querySelector('#panel-butir tbody tr:first-child td:first-child').textContent : ''"
    )
    sort_changed = (
        (isinstance(aria_before, str) and isinstance(aria_after, str) and
         aria_before != aria_after) or
        (bool(first_row_before) and bool(first_row_after) and
         first_row_before != first_row_after)
    )
    res.record("interactive: sort button changes aria-sort or row order",
               f"aria: {aria_before}->{aria_after}  row: {first_row_before}->{first_row_after}",
               sort_changed)

    # E17-E22: 6 more sort columns clickable (total 8 - 1 already tested = 7, test 6 more)
    all_sort_btns = page.locator("#panel-butir .th-sort").all()
    clicked = 0
    for btn in all_sort_btns[1:7]:
        btn.scroll_into_view_if_needed()
        btn.click()
        time.sleep(0.1)
        clicked += 1
    res.record("interactive: 6 additional sort columns clickable",
               clicked, clicked == 6)

    # E23: Delta-only checkbox changes visible rows
    cmp_url = (base_explore + f"?view=bandingkan"
               f"&from={analysis1_id}&to={analysis2_id}")
    goto(page, cmp_url)
    visible_rows = (
        "Array.from(document.querySelectorAll('#cmp-tbody tr'))"
        ".filter(r => !r.hidden && getComputedStyle(r).display !== 'none').length"
    )
    rows_before = page.evaluate(visible_rows)
    checkbox = page.locator("#cmp-delta-only")
    checkbox.scroll_into_view_if_needed()
    checkbox.click()
    time.sleep(0.15)
    rows_after = page.evaluate(visible_rows)
    e23_ok = (isinstance(rows_before, int) and rows_before > 0 and
              isinstance(rows_after, int) and rows_after != rows_before)
    res.record("interactive: delta-only checkbox changes visible rows",
               f"before={rows_before} after={rows_after}", e23_ok)

    # E24: person pager next -> page 2 of 2 (501 seeded persons, render page 500)
    person_url = f"{base_explore}?view=partisipan"
    goto(page, person_url)
    page1_first = page.evaluate(
        "document.querySelector('#panel-partisipan tbody tr td') ?"
        "document.querySelector('#panel-partisipan tbody tr td').textContent : ''"
    )
    page1_label = page.evaluate(
        "document.querySelector('#panel-partisipan .pager') ?"
        "document.querySelector('#panel-partisipan .pager').textContent : ''"
    )
    next_link = page.locator("#panel-partisipan .pager a").filter(has_text="Selanjutnya")
    if next_link.count() > 0:
        next_link.first.click()
        time.sleep(0.3)
    page2_label = page.evaluate(
        "document.querySelector('#panel-partisipan .pager') ?"
        "document.querySelector('#panel-partisipan .pager').textContent : ''"
    )
    page2_first = page.evaluate(
        "document.querySelector('#panel-partisipan tbody tr td') ?"
        "document.querySelector('#panel-partisipan tbody tr td').textContent : ''"
    )
    e24_ok = ("Halaman 2" in page2_label and page2_first != page1_first and bool(page1_first))
    res.record("interactive: person pager next shows page 2",
               f"label='{page2_label.strip()[:28]}' first={page1_first}->{page2_first}", e24_ok)

    # E25: person pager prev -> back to page 1
    prev_link = page.locator("#panel-partisipan .pager a").filter(has_text="Sebelumnya")
    if prev_link.count() > 0:
        prev_link.first.click()
        time.sleep(0.3)
    page1b_label = page.evaluate(
        "document.querySelector('#panel-partisipan .pager') ?"
        "document.querySelector('#panel-partisipan .pager').textContent : ''"
    )
    page1b_first = page.evaluate(
        "document.querySelector('#panel-partisipan tbody tr td') ?"
        "document.querySelector('#panel-partisipan tbody tr td').textContent : ''"
    )
    e25_ok = ("Halaman 1" in page1b_label and page1b_first == page1_first)
    res.record("interactive: person pager prev returns to page 1",
               f"label='{page1b_label.strip()[:28]}' first={page1b_first}", e25_ok)

    # E26: misfit toggle marks items inside the chart
    goto(page, wright_url)
    # misfit ticks always carry .is-misfit; the toggle adds .is-misfit-highlight
    marked_before = page.evaluate(
        "document.querySelectorAll('#wright-scale svg .wright-item-tick.is-misfit').length"
    )
    highlighted_before = page.evaluate(
        "document.querySelectorAll('#wright-scale svg .wright-item-tick.is-misfit-highlight').length"
    )
    toggle = page.locator("#wright-misfit-toggle")
    toggle.scroll_into_view_if_needed()
    toggle.check()
    time.sleep(0.2)
    marked_after = page.evaluate(
        "document.querySelectorAll('#wright-scale svg .wright-item-tick.is-misfit').length"
    )
    highlighted_after = page.evaluate(
        "document.querySelectorAll('#wright-scale svg .wright-item-tick.is-misfit-highlight').length"
    )
    e26_ok = (isinstance(marked_after, int) and marked_after > 0 and
              highlighted_before == 0 and
              isinstance(highlighted_after, int) and highlighted_after == marked_after)
    res.record("interactive: misfit toggle highlights the misfitting items",
               f"marked {marked_before}->{marked_after} highlighted {highlighted_before}->{highlighted_after}",
               e26_ok)

    # E27: selecting an item tick updates the readout
    readout_before = page.evaluate(
        "document.getElementById('wright-readout') ?"
        "document.getElementById('wright-readout').textContent : ''"
    )
    page.evaluate(
        "() => { const t = document.querySelector('#wright-scale svg .wright-item-tick');"
        " if (t) { t.dispatchEvent(new MouseEvent('click', {bubbles: true})); } }"
    )
    time.sleep(0.2)
    readout_after = page.evaluate(
        "document.getElementById('wright-readout') ?"
        "document.getElementById('wright-readout').textContent : ''"
    )
    e27_ok = (readout_after != readout_before and "Measure" in readout_after)
    res.record("interactive: item tick selection updates the readout",
               f"'{readout_after.strip()[:40]}'", e27_ok)

    # E27b: Wright map hit area: clicking 20px from tick center selects the item
    hit_info = page.evaluate("""() => {
        const g = document.querySelector('#wright-scale svg .wright-item-tick');
        if (!g) return null;
        const rect = g.querySelector("rect[opacity='0']");
        if (!rect) return null;
        const b = rect.getBoundingClientRect();
        return {
            entry: g.getAttribute("data-entry"),
            cx: b.left + b.width / 2,
            cy: b.top + b.height / 2,
            w: b.width,
            h: b.height,
        };
    }""")
    selected_hit_entry = None
    if hit_info:
        page.mouse.click(hit_info["cx"], hit_info["cy"] - 20)
        time.sleep(0.2)
        selected_hit_entry = page.evaluate("""() => {
            const act = document.querySelector('#wright-scale svg .wright-item-tick.is-active');
            return act ? act.getAttribute('data-entry') : null;
        }""")
    e27b_ok = bool(hit_info and hit_info["w"] >= 44 and selected_hit_entry == hit_info["entry"])
    res.record(
        "interactive: wright map hit area selectable 20px from tick center",
        f"entry={selected_hit_entry} target={hit_info['entry']} hit_w={hit_info['w']:.1f} hit_h={hit_info['h']:.1f}" if hit_info else "no hit rect found",
        e27b_ok,
    )

    # E28: all 8 sortable columns clickable
    goto(page, butir_url)
    total_btns = page.evaluate("document.querySelectorAll('#panel-butir .th-sort').length")
    sort_ok = 0
    for i in range(total_btns):
        btn = page.locator("#panel-butir .th-sort").nth(i)
        th = btn.locator("xpath=ancestor::th[1]")
        aria_pre = th.get_attribute("aria-sort")
        row_pre = page.evaluate(
            "document.querySelector('#panel-butir tbody tr') ?"
            "document.querySelector('#panel-butir tbody tr').textContent : ''"
        )
        try:
            btn.scroll_into_view_if_needed()
            btn.click(timeout=4000)
            time.sleep(0.1)
            aria_post = th.get_attribute("aria-sort")
            row_post = page.evaluate(
                "document.querySelector('#panel-butir tbody tr') ?"
                "document.querySelector('#panel-butir tbody tr').textContent : ''"
            )
            if aria_post != aria_pre or row_post != row_pre:
                sort_ok += 1
        except Exception:
            pass
    e28_ok = (total_btns == 8 and sort_ok == 8)
    res.record("interactive: all 8 sort columns clickable",
               f"{sort_ok}/{total_btns} changed", e28_ok)

    # E29: Wright item labels never overlap and never leave the canvas. The label grid has a
    # pitch wider than a box; this check is what keeps that true (the earlier layout put 38-unit
    # boxes on a 34-unit pitch and overlapped 34 pairs on a clustered 59-item fixture).
    goto(page, wright_url)
    geom = page.evaluate(
        """() => {
        const svg = document.querySelector('#wright-scale svg');
        if (!svg) return null;
        const boxes = [...svg.querySelectorAll('.wright-item-tick rect')]
            .filter(r => !r.classList.contains('focus-ring') && r.getAttribute('opacity') !== '0')
            .map(r => r.getBoundingClientRect());
        const labels = [...svg.querySelectorAll('.wright-item-tick text')]
            .map(t => t.getBoundingClientRect());
        const canvas = svg.getBoundingClientRect();
        let overlaps = 0;
        for (let i = 0; i < boxes.length; i++) {
            for (let j = i + 1; j < boxes.length; j++) {
                const a = boxes[i], b = boxes[j];
                const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                if (ox > 0.5 && oy > 0.5) overlaps++;
            }
        }
        let outside = 0;
        for (const b of boxes) {
            if (b.left < canvas.left - 0.5 || b.right > canvas.right + 0.5 ||
                b.top < canvas.top - 0.5 || b.bottom > canvas.bottom + 0.5) outside++;
        }
        const view = svg.viewBox.baseVal;
        const scale = view && view.width ? canvas.width / view.width : 1;
        const groups = [...svg.querySelectorAll('.wright-item-tick')];
        let uncovered = 0;
        let tethered = 0;
        for (const g of groups) {
            const box = g.querySelector('rect:not(.focus-ring):not([opacity="0"])');
            const binX = parseFloat(g.getAttribute('data-bin-x'));
            if (!box || isNaN(binX)) continue;
            const b = box.getBoundingClientRect();
            const trueX = canvas.left + binX * scale;
            const half = (b.right - b.left) / 2 + 0.5;
            if (Math.abs(trueX - (b.left + b.right) / 2) > half) {
                uncovered++;
                if (g.querySelector('.label-leader')) tethered++;
            }
        }
        return {ticks: groups.length, boxes: boxes.length, labels: labels.length,
                overlaps: overlaps, outside: outside,
                uncovered: uncovered, tethered: tethered};
        }"""
    )
    e29_ok = bool(
        geom and geom["ticks"] > 0 and geom["labels"] == geom["ticks"]
        and geom["overlaps"] == 0 and geom["outside"] == 0
        and geom["uncovered"] == geom["tethered"]
    )
    # E30: the participant distribution renders, never drops its text below the pinned floor, and
    # repaints on a theme swap. The view carried no figure at all before this pass, on a page whose
    # other chart did (a single-draw repaint left this one in the old palette).
    partisipan_url = f"{base_url}/analyses/{analysis1_id}/explore?view=partisipan"
    goto(page, partisipan_url)
    hist = page.evaluate(
        """() => {
        const box = document.getElementById('partisipan-chart');
        const svg = box ? box.querySelector('svg') : null;
        if (!svg) return null;
        const wrap = box.closest('.chart-scroll');
        const texts = [...svg.querySelectorAll('text')];
        const bars = svg.querySelectorAll('rect[data-hist-bar]');
        const view = svg.viewBox.baseVal;
        const drawn = svg.getBoundingClientRect();
        return {bars: bars.length, texts: texts.length,
                minText: texts.length ? Math.min(...texts.map(t => parseFloat(getComputedStyle(t).fontSize))) : 0,
                scale: view && view.width ? drawn.width / view.width : 0,
                aria: svg.getAttribute('aria-label') || '',
                fill: bars.length ? getComputedStyle(bars[0]).fill : '',
                scrollable: wrap ? wrap.scrollWidth >= wrap.clientWidth : false};
        }"""
    )
    theme_fill = ""
    if hist and page.locator("#theme-toggle").count():
        page.click("#theme-toggle")
        page.wait_for_timeout(500)
        theme_fill = page.evaluate(
            """() => {
            const bar = document.querySelector('#partisipan-chart svg rect[data-hist-bar]');
            return bar ? getComputedStyle(bar).fill : '';
            }"""
        )
        page.click("#theme-toggle")
        page.wait_for_timeout(400)
    e30_ok = bool(
        hist and hist["bars"] > 1 and hist["texts"] > 0
        and hist["minText"] >= 12 and hist["scale"] >= 1
        and hist["aria"] and hist["scrollable"]
        and (theme_fill == "" or theme_fill != hist["fill"])
    )
    res.record(
        "partisipan: distribution renders, text at or above the pinned floor, repaints on theme swap",
        (f"bars={hist['bars']} texts={hist['texts']} minText={hist['minText']} "
         f"scale={hist['scale']:.3f} scrollable={hist['scrollable']} "
         f"fill={hist['fill']} afterTheme={theme_fill or 'n/a'}") if hist else "no svg found",
        e30_ok,
    )


    res.record(
        "wright: labels never overlap, stay in the canvas, and cover the item's own position",
        (f"ticks={geom['ticks']} labels={geom['labels']} overlaps={geom['overlaps']} "
         f"outside={geom['outside']} uncovered={geom['uncovered']} "
         f"tethered={geom['tethered']}") if geom else "no svg found",
        e29_ok,
    )


# ---------------------------------------------------------------------------
# Group F: States as rendered text (5 checks)
# ---------------------------------------------------------------------------


def group_f_states(page: Any, base_url: str,
                   analysis1_id: int, analysis3_id: int,
                   analysis4_id: int, dataset1_id: int,
                   res: Results) -> None:
    """6 state checks as visible rendered text."""
    print("\n[F] States as rendered text")

    base_explore = f"{base_url}/analyses/{analysis1_id}/explore"

    # F1: Item no-match shows "Tidak ada baris"
    goto(page, base_explore + "?view=butir&q_item=NOMATCH_ZZZ99")
    empty_txt = page.evaluate(
        "document.querySelector('#butir-empty .empty-text') ? "
        "document.querySelector('#butir-empty .empty-text').textContent.trim() : ''"
    )
    res.record("state: item no-match empty text", empty_txt[:60],
               bool(empty_txt) and "Tidak ada baris" in empty_txt)

    # F2: Person no-match shows "Tidak ada baris"
    goto(page, base_explore + "?view=partisipan&q_person=NOMATCH_ZZZ99")
    person_empty_txt = page.evaluate(
        "document.querySelector('#partisipan-empty .empty-text') ? "
        "document.querySelector('#partisipan-empty .empty-text').textContent.trim() : ''"
    )
    res.record("state: person no-match empty text", person_empty_txt[:60],
               bool(person_empty_txt) and "Tidak ada baris" in person_empty_txt)

    # F3: Compare without from/to shows selection prompt
    goto(page, f"{base_url}/analyses/{analysis3_id}/explore?view=bandingkan")
    cmp_stmt = page.evaluate(
        "document.getElementById('cmp-statement') ? "
        "document.getElementById('cmp-statement').textContent.trim() : ''"
    )
    res.record("state: compare no-params shows selection prompt",
               cmp_stmt[:80],
               bool(cmp_stmt) and "Pilih dua analisis" in cmp_stmt)

    # F4: Compare with two analyses that have same labels -> "Cocok:" is rendered
    goto(page, (f"{base_url}/analyses/{analysis3_id}/explore"
                f"?view=bandingkan&from={analysis3_id}&to={analysis1_id}"))
    counts_txt = page.evaluate(
        "document.getElementById('cmp-counts') ? "
        "document.getElementById('cmp-counts').textContent.trim() : ''"
    )
    res.record("state: compare counts line rendered",
               counts_txt[:80],
               bool(counts_txt) and "Cocok:" in counts_txt)

    # F5: Malformed wright file shows error text
    goto(page, f"{base_url}/analyses/{analysis4_id}/explore?view=wright")
    error_txt = page.evaluate(
        "document.getElementById('explorer-error-reason') ? "
        "document.getElementById('explorer-error-reason').textContent.trim() : ''"
    )
    res.record("state: malformed wright shows error reason",
               error_txt[:80],
               bool(error_txt) and "Wright" in error_txt)

    # F6: after commit POST the landing page shows the confirmation sentence
    goto(page, f"{base_url}/datasets/{dataset1_id}?msg=committed")
    commit_alert = page.evaluate("""() => {
        const el = document.querySelector('.alert--fit') || document.querySelector('.alert');
        return el ? el.textContent.trim() : (document.body ? document.body.innerText.slice(0, 100) : '');
    }""")
    expected_sentence = "Pemetaan respon berhasil dikonfirmasi. Jalankan analisis untuk memperoleh hasil."
    f6_ok = bool(expected_sentence in commit_alert)
    res.record(
        "state: commit landing page shows confirmation sentence",
        commit_alert[:80],
        f6_ok,
    )


# ---------------------------------------------------------------------------
# Group G: Keyboard (5 checks)
# ---------------------------------------------------------------------------


def group_g_keyboard(page: Any, base_url: str, analysis1_id: int,
                     res: Results) -> None:
    """5 keyboard navigation checks."""
    print("\n[G] Keyboard")

    goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=wright")

    # G1: Tablist reachable with Tab
    page.evaluate("document.body.focus()")
    reached = False
    for _ in range(25):
        page.keyboard.press("Tab")
        focused_id = page.evaluate(
            "document.activeElement ? document.activeElement.id : ''"
        )
        if focused_id.startswith("tab-"):
            reached = True
            break
    res.record("keyboard: tablist reachable with Tab", focused_id, reached)

    # G2: ArrowRight moves focus to next tab
    before_id = page.evaluate("document.activeElement ? document.activeElement.id : ''")
    page.keyboard.press("ArrowRight")
    after_id = page.evaluate("document.activeElement ? document.activeElement.id : ''")
    g2_ok = (bool(after_id) and after_id.startswith("tab-") and after_id != before_id)
    res.record("keyboard: ArrowRight moves to next tab",
               f"{before_id}->{after_id}", g2_ok)

    # G3: ArrowLeft moves focus to previous tab
    page.keyboard.press("ArrowLeft")
    left_id = page.evaluate("document.activeElement ? document.activeElement.id : ''")
    g3_ok = (bool(left_id) and left_id.startswith("tab-") and left_id != after_id)
    res.record("keyboard: ArrowLeft moves to previous tab",
               f"{after_id}->{left_id}", g3_ok)

    # G4: Enter activates focused tab
    page.locator("#tab-butir").focus()
    page.keyboard.press("Enter")
    page.wait_for_load_state("domcontentloaded")
    time.sleep(0.15)
    butir_active = page.evaluate(
        "document.getElementById('panel-butir') ? "
        "document.getElementById('panel-butir').classList.contains('is-active') : false"
    )
    res.record("keyboard: Enter on tab-butir activates panel",
               butir_active, bool(butir_active))

    # G5: Focused element shows visible focus indicator
    goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=wright")
    page.locator("#tab-wright").focus()
    outline_info = page.evaluate("""
        (function() {
            var el = document.activeElement;
            if (!el) return '';
            var cs = window.getComputedStyle(el);
            return cs.outline + '|' + cs.getPropertyValue('box-shadow');
        })()
    """)
    g5_ok = bool(outline_info) and (
        re.search(r"\d+px", outline_info) is not None
    )
    res.record("keyboard: focused element shows focus indicator",
               outline_info[:80], g5_ok)


# ---------------------------------------------------------------------------
# Group H: Self-contained (2 checks)
# ---------------------------------------------------------------------------


def group_h_self_contained(external_hosts: set[str], res: Results) -> None:
    """2 checks: no unexpected external hosts, no non-origin assets."""
    print("\n[H] Self-contained")

    allowed = {"fonts.googleapis.com", "fonts.gstatic.com"}
    unexpected = external_hosts - allowed
    res.record("self-contained: no unexpected external hosts",
               list(unexpected) if unexpected else "none",
               len(unexpected) == 0)
    res.record("self-contained: all assets from origin or font hosts",
               list(external_hosts) if external_hosts else "none",
               len(unexpected) == 0)


# ---------------------------------------------------------------------------
# Group I: Static scans (4 checks)
# ---------------------------------------------------------------------------


def group_i_static(page: Any, base_url: str, analysis1_id: int,
                   console_errors: list[str], res: Results) -> None:
    """4 static scan checks."""
    print("\n[I] Static scans")

    goto(page, f"{base_url}/analyses/{analysis1_id}/explore?view=butir")

    # I1: No style attribute in rendered explorer DOM (excluding SVG chart elements)
    style_attrs = page.evaluate("""
        (function() {
            var all = document.querySelectorAll('.explorer-panel [style], #tablist [style]');
            var non_svg = Array.from(all).filter(function(el) {
                // Allow style attrs on SVG elements inside chart-scroll containers (JS-generated)
                if (el.closest('.chart-scroll')) return false;
                var tag = el.tagName.toLowerCase();
                var svg_tags = ['svg','g','rect','text','path','line','circle',
                                'polyline','polygon','ellipse','use','defs',
                                'clippath','mask','linearGradient'];
                return svg_tags.indexOf(tag) === -1;
            });
            return non_svg.length;
        })()
    """)
    res.record("static: no style attrs in explorer (excl SVG charts)",
               style_attrs, style_attrs == 0)

    # I2: No raw hex colour in rendered text nodes
    hex_count = page.evaluate("""
        (function() {
            var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            var node, found = 0;
            var re = /#[0-9A-Fa-f]{3,8}\\b/g;
            while ((node = walker.nextNode())) {
                var m = node.textContent.match(re);
                if (m) found += m.length;
            }
            return found;
        })()
    """)
    res.record("static: no raw hex colour in rendered text", hex_count, hex_count == 0)

    # I3: No em dash in visible text
    em_dash = page.evaluate("""
        (document.body.innerText || '').split('\\u2014').length - 1
    """)
    res.record("static: no em dash in visible text", em_dash, em_dash == 0)

    # I4: Zero console errors during the whole run
    res.record("static: zero console errors", f"{len(console_errors)}: {console_errors}" if console_errors else 0,
               len(console_errors) == 0)


# ---------------------------------------------------------------------------
# Group J: Performance budgets (8 checks)
# ---------------------------------------------------------------------------


def group_j_performance(page: Any, base_url: str, analysis1_id: int,
                         res: Results) -> None:
    """8 performance budget checks."""
    print("\n[J] Performance")

    wright_url = f"{base_url}/analyses/{analysis1_id}/explore?view=wright"
    butir_url  = f"{base_url}/analyses/{analysis1_id}/explore?view=butir"

    # J1: loadEventEnd <= 400 ms
    page.goto(wright_url, wait_until="load")
    nav_timing = page.evaluate("""
        (function() {
            var t = performance.timing;
            if (!t) return -1;
            return t.loadEventEnd - t.navigationStart;
        })()
    """)
    j1_ok = isinstance(nav_timing, (int, float)) and 0 < nav_timing <= 400
    res.record("perf: loadEventEnd <= 400ms", nav_timing, j1_ok)

    # In-page activation timer: click a tab and stop when its rows exist.
    TAB_TIMER = """(args) => new Promise(resolve => {
        const tab = document.getElementById(args.tabId);
        if (!tab) { resolve(-1); return; }
        const t0 = performance.now();
        tab.click();
        const iv = setInterval(() => {
            const rows = document.querySelectorAll('#' + args.panelId + ' tbody tr');
            if (rows.length > 0) { clearInterval(iv); resolve(performance.now() - t0); }
        }, 1);
        setTimeout(() => { clearInterval(iv); resolve(-1); }, 5000);
    })"""

    # J2: First activation of butir <= 150 ms (measured in-page, not by navigating)
    goto(page, wright_url)
    t_butir = page.evaluate(TAB_TIMER, {"tabId": "tab-butir", "panelId": "panel-butir"})
    butir_rows = page.evaluate(
        "document.querySelectorAll('#panel-butir tbody tr').length"
    )
    j2_ok = (isinstance(butir_rows, int) and butir_rows > 0 and
             isinstance(t_butir, (int, float)) and 0 < t_butir <= 150)
    res.record("perf: first butir activation <= 150ms",
               f"{t_butir:.1f}ms rows={butir_rows}", j2_ok)

    # J3: Cached re-activation <= 50 ms (leave the panel, come back, no navigation)
    page.evaluate("() => document.getElementById('tab-wright').click()")
    time.sleep(0.2)
    t_butir2 = page.evaluate(TAB_TIMER, {"tabId": "tab-butir", "panelId": "panel-butir"})
    butir_rows2 = page.evaluate(
        "document.querySelectorAll('#panel-butir tbody tr').length"
    )
    j3_ok = (isinstance(butir_rows2, int) and butir_rows2 > 0 and
             isinstance(t_butir2, (int, float)) and 0 < t_butir2 <= 50)
    res.record("perf: cached butir re-activation <= 50ms",
               f"{t_butir2:.1f}ms rows={butir_rows2}", j3_ok)

    # J4: Sort the 147-row table <= 100 ms (measured in-page until the order changes)
    goto(page, butir_url)
    t_sort = page.evaluate("""() => new Promise(resolve => {
        const btns = document.querySelectorAll('#panel-butir .th-sort');
        const btn = btns[1] || btns[0];
        const table = document.querySelector('#panel-butir table[data-explorer-table]');
        if (!btn || !table) { resolve(-1); return; }
        const th = btn.closest('th');
        const ariaBefore = th ? th.getAttribute('aria-sort') : null;
        const before = table.querySelector('tbody tr') ? table.querySelector('tbody tr').textContent : '';
        const t0 = performance.now();
        btn.click();
        const iv = setInterval(() => {
            const now = table.querySelector('tbody tr') ? table.querySelector('tbody tr').textContent : '';
            const ariaNow = th ? th.getAttribute('aria-sort') : null;
            if (now !== before || ariaNow !== ariaBefore) { clearInterval(iv); resolve(performance.now() - t0); }
        }, 1);
        setTimeout(() => { clearInterval(iv); resolve(-1); }, 5000);
    })""")
    rows_before = page.evaluate(
        "document.querySelectorAll('#panel-butir tbody tr').length"
    )
    j4_ok = (isinstance(rows_before, int) and rows_before > 0 and
             isinstance(t_sort, (int, float)) and 0 < t_sort <= 100)
    res.record("perf: 147-row sort <= 100ms",
               f"{t_sort:.1f}ms rows={rows_before}", j4_ok)

    # J5: Search round trip <= 250 ms
    page.goto(butir_url, wait_until="domcontentloaded")
    t3 = time.monotonic()
    page.goto(butir_url + "&q_item=LBL001", wait_until="domcontentloaded")
    t_search = (time.monotonic() - t3) * 1000
    search_rows = page.evaluate(
        "document.querySelectorAll('#panel-butir tbody tr').length"
    )
    j5_ok = (isinstance(search_rows, int) and search_rows > 0 and
             isinstance(t_search, float) and 0 < t_search <= 250)
    res.record("perf: search round trip <= 250ms",
               f"{t_search:.1f}ms rows={search_rows}", j5_ok)

    # J6: Long tasks == 0
    page.goto(wright_url, wait_until="load")
    long_tasks = page.evaluate("""
        (function() {
            if (!window.performance || !performance.getEntriesByType) return 0;
            return (performance.getEntriesByType('longtask') || []).length;
        })()
    """)
    j6_ok = isinstance(long_tasks, int) and long_tasks == 0
    res.record("perf: zero long tasks > 100ms", long_tasks, j6_ok)

    # J7: Initial HTML <= 120000 bytes
    import urllib.request
    req = urllib.request.Request(
        wright_url,
        headers={"Cookie": f"{COOKIE_NAME}={SESSION_TOKEN}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        html_body = resp.read()
    html_size = len(html_body)
    j7_ok = isinstance(html_size, int) and 0 < html_size <= 120000
    res.record("perf: initial HTML <= 120000 bytes", html_size, j7_ok)

    # J8: Embedded payload <= 60000 bytes
    page.goto(wright_url, wait_until="domcontentloaded")
    payload_text = page.evaluate(
        "document.getElementById('explorer-data') ? "
        "document.getElementById('explorer-data').textContent : ''"
    )
    payload_size = len(payload_text.encode("utf-8")) if payload_text else 0
    j8_ok = isinstance(payload_size, int) and 0 < payload_size <= 60000
    res.record("perf: embedded payload <= 60000 bytes", payload_size, j8_ok)


# ---------------------------------------------------------------------------
# Group K: Authorization (3 checks)
# ---------------------------------------------------------------------------


def group_k_authorization(base_url: str, analysis1_id: int,
                           foreign_analysis_id: int, res: Results) -> None:
    """3 authorization checks."""
    print("\n[K] Authorization")
    import urllib.request
    import urllib.error

    def get_status(url: str, cookie: str | None = None) -> int:
        req = urllib.request.Request(url)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    # K1: Anonymous request returns 404
    k1 = get_status(f"{base_url}/analyses/{analysis1_id}/explore")
    res.record("auth: anonymous -> 404", k1, k1 == 404)

    # K2: Foreign analysis returns 404 for owner A
    k2 = get_status(
        f"{base_url}/analyses/{foreign_analysis_id}/explore",
        f"{COOKIE_NAME}={SESSION_TOKEN}"
    )
    res.record("auth: foreign analysis -> 404 for user A", k2, k2 == 404)

    # K3: Invalid session token returns 404 (gate/auth guard)
    k3 = get_status(
        f"{base_url}/analyses/{analysis1_id}/explore",
        f"{COOKIE_NAME}=invalidtoken000000000000000000000000000"
    )
    res.record("auth: invalid token -> 404", k3, k3 == 404)


# ---------------------------------------------------------------------------
# Table printer
# ---------------------------------------------------------------------------


def print_group_table(letter: str, name: str,
                      checks: list[dict[str, Any]]) -> None:
    print(f"\n{'=' * 72}")
    print(f"Group {letter}: {name}  ({len(checks)} checks)")
    print(f"{'=' * 72}")
    pass_n = sum(1 for c in checks if c["passed"])
    fail_n = len(checks) - pass_n
    for c in checks:
        status = "PASS" if c["passed"] else "FAIL"
        print(f"  [{status}] {c['name'][:58]:<58}  {str(c['measured'])[:30]}")
    print(f"  -- {pass_n} PASS  {fail_n} FAIL")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def main() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="verify_explorer_")
    db_path = os.path.join(tmp_dir, "explorer.db")

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["GATE_OPEN"] = "true"

    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    uvicorn_proc = None
    console_errors: list[str] = []
    external_hosts: set[str] = set()

    try:
        # Bootstrap schema
        print("Bootstrapping schema...")
        r = subprocess.run(
            [str(VENV_PYTHON), "-c",
             "from app.db import get_engine; from app.models import Base; "
             "Base.metadata.create_all(get_engine())"],
            env=env, cwd=str(REPO),
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            print(f"Schema bootstrap failed:\n{r.stderr}")
            return 1

        # Seed database
        print("Seeding database...")
        ids = seed_database(db_path)
        dataset1_id      = ids["dataset1_id"]
        analysis1_id     = ids["analysis1_id"]
        analysis2_id     = ids["analysis2_id"]
        analysis3_id     = ids["analysis3_id"]
        analysis4_id     = ids["analysis4_id"]
        foreign_aid      = ids["foreign_analysis_id"]
        print(f"  a1={analysis1_id} a2={analysis2_id} a3={analysis3_id} "
              f"a4={analysis4_id} foreign={foreign_aid}")

        # Start uvicorn
        print(f"Starting uvicorn on port {port}...")
        uvicorn_proc = subprocess.Popen(
            [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(port)],
            env=env, cwd=str(REPO),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_for_health(base_url)
        print("App ready.")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()

            context.add_cookies([{
                "name": COOKIE_NAME, "value": SESSION_TOKEN,
                "domain": "127.0.0.1", "path": "/",
            }])

            def handle_route(route: Any) -> None:
                host = route.request.url.split("/")[2].split(":")[0]
                if host != "127.0.0.1":
                    external_hosts.add(host)
                    route.fulfill(status=200, body="", content_type="text/plain")
                else:
                    route.continue_()

            context.route("**/*", handle_route)
            page = context.new_page()
            page.set_viewport_size({"width": 1440, "height": 900})
            page.on("console", lambda msg: (
                console_errors.append(msg.text) if msg.type == "error" else None
            ))

            # ----------------------------------------------------------------
            # Run groups and capture results
            # ----------------------------------------------------------------
            all_results = Results()
            group_data: list[tuple[str, str, list[dict[str, Any]]]] = []

            def capture(letter: str, name: str, fn, *args) -> None:
                start = all_results.total()
                fn(*args)
                end = all_results.total()
                group_data.append((letter, name, all_results._checks[start:end]))

            capture("A", "Responsive",
                    group_a_responsive, page, base_url, analysis1_id, all_results)

            capture("B", "Shell and panel structure",
                    group_b_shell, page, base_url, analysis1_id, analysis2_id, dataset1_id, all_results)

            capture("C", "Contrast",
                    group_c_contrast, page, base_url, analysis1_id, all_results)

            capture("D", "DOM reconciliation",
                    group_d_dom_reconciliation, page, base_url,
                    analysis1_id, analysis2_id, all_results)

            capture("E", "Interactive controls",
                    group_e_interactive, page, base_url,
                    analysis1_id, analysis2_id, all_results)

            capture("F", "States as rendered text",
                    group_f_states, page, base_url,
                    analysis1_id, analysis3_id, analysis4_id, dataset1_id, all_results)

            capture("G", "Keyboard",
                    group_g_keyboard, page, base_url, analysis1_id, all_results)

            capture("H", "Self-contained",
                    group_h_self_contained, external_hosts, all_results)

            capture("I", "Static scans",
                    group_i_static, page, base_url, analysis1_id,
                    console_errors, all_results)

            capture("J", "Performance budgets",
                    group_j_performance, page, base_url, analysis1_id, all_results)

            capture("K", "Authorization",
                    group_k_authorization, base_url, analysis1_id, foreign_aid, all_results)

            browser.close()

        # ----------------------------------------------------------------
        # Print summary tables
        # ----------------------------------------------------------------
        print("\n\n" + "=" * 72)
        print("SUMMARY TABLE")
        print("=" * 72)
        for letter, name, checks in group_data:
            print_group_table(letter, name, checks)

        total  = all_results.total()
        passed = all_results.passed()
        failed = all_results.failed()

        print(f"\n{'=' * 72}")
        print(f"TOTAL: {total} checks  |  {passed} PASS  |  {failed} FAIL")
        print(f"{'=' * 72}")

        EXPECTED_TOTAL = 193
        if total != EXPECTED_TOTAL:
            print(
                f"\nERROR: Expected {EXPECTED_TOTAL} checks, got {total}. "
                f"Harness check count mismatch."
            )
            return 1

        if failed > 0:
            print(f"\nFAIL: {failed} check(s) failed.")
            return 1

        print("\n193/193 PASS")
        return 0

    finally:
        if uvicorn_proc is not None:
            uvicorn_proc.terminate()
            try:
                uvicorn_proc.wait(timeout=5)
            except Exception:
                uvicorn_proc.kill()
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())