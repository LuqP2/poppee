"""Tests for the display, positioning, demo, and state logic (no GUI display needed)."""

from concurrent.futures import ThreadPoolExecutor

from conftest import make_message

from poppee.checker import AccountResult
from poppee.config import Account
from poppee.icon import render_icon
from poppee.preview import as_text, format_age, load_sections
from poppee.state import State
from poppee.ui.app import tray_tooltip
from poppee.ui.demo import build_demo_checker
from poppee.ui.layout_math import (
    Rect,
    clamp_bubble_pos,
    compute_panel_pos,
    default_bubble_pos,
    detect_dock_edge,
    docked_bubble_x,
    format_badge,
)
from poppee.ui.query_builder import FilterSpec, build_query, parse_query

A = Account(email="a@gmail.com", name="Alpha")
B = Account(email="b@gmail.com", name="Beta")


def test_tray_tooltip():
    ok = AccountResult(A, unread=3, more=True)
    bad = AccountResult(B, error="Sign-in needed: token revoked")
    assert "3" in tray_tooltip([ok, bad]) and "erro" in tray_tooltip([ok, bad])
    assert "sem contas" in tray_tooltip([])
    assert len(tray_tooltip([AccountResult(A, error="x")] * 50)) <= 63


def test_format_badge():
    assert format_badge(0) == ""
    assert format_badge(-2) == ""
    assert format_badge(3) == "3"
    assert format_badge(12, more=True) == "12+"
    assert format_badge(99, more=True) == "99+"
    assert format_badge(140) == "99+"


def test_bubble_positioning_and_docking():
    screen = Rect(0, 0, 1920, 1080)
    dx, dy = default_bubble_pos(80, 44, screen)
    assert dx == 1920 - 80 - 20 and dy == 24

    assert clamp_bubble_pos(-50, -20, 80, 44, screen) == (8, 8)
    assert clamp_bubble_pos(2500, 1500, 80, 44, screen) == (1920 - 80 - 8, 1080 - 44 - 8)

    assert detect_dock_edge(10, 80, screen) == "left"
    assert detect_dock_edge(1830, 80, screen) == "right"
    assert detect_dock_edge(900, 80, screen) is None

    # Right edge peeking vs expanded
    assert docked_bubble_x("right", 1830, 80, screen, peek=24, expanded=False) == 1920 - 24
    assert docked_bubble_x("right", 1830, 80, screen, peek=24, expanded=True) == 1920 - 80 - 10

    # Left edge peeking vs expanded
    assert docked_bubble_x("left", 10, 80, screen, peek=24, expanded=False) == -80 + 24
    assert docked_bubble_x("left", 10, 80, screen, peek=24, expanded=True) == 10


def test_panel_anchoring_all_corners():
    screen = Rect(0, 0, 1920, 1080)
    pw, ph = 360, 400

    # Top-right bubble -> panel right-aligned and below
    px, py = compute_panel_pos(Rect(1820, 24, 80, 44), pw, ph, screen)
    assert px == 1900 - pw and py == 24 + 44 + 8

    # Top-left bubble -> panel left-aligned and below
    px, py = compute_panel_pos(Rect(20, 24, 80, 44), pw, ph, screen)
    assert px == 20 and py == 24 + 44 + 8

    # Bottom-right bubble -> panel flips above bubble
    px, py = compute_panel_pos(Rect(1820, 1000, 80, 44), pw, ph, screen)
    assert px == 1900 - pw and py == 1000 - ph - 8

    # Bottom-left bubble -> panel left-aligned and above
    px, py = compute_panel_pos(Rect(20, 1000, 80, 44), pw, ph, screen)
    assert px == 20 and py == 1000 - ph - 8


def test_render_icon():
    for count in (0, 7, 42, 1234):
        img = render_icon(count, size=64)
        assert img.size == (64, 64) and img.mode == "RGBA"
    assert render_icon(0, size=64).tobytes() != render_icon(5, size=64).tobytes()


def test_format_age():
    assert format_age(100, now=130) == "now"
    assert format_age(0, now=300) == "5m"
    assert format_age(0, now=7200) == "2h"
    assert format_age(0, now=86400 * 3) == "3d"
    assert format_age(0, now=86400 * 15) == "2w"


def test_preview_reads_state(tmp_path):
    state = State(tmp_path / "state.json")
    st = state.account("a@gmail.com")
    st.update(name="Alpha", email="a@gmail.com", unread=1, recent=[make_message("1").to_dict()])
    state.save()
    (section,) = load_sections(tmp_path / "state.json")
    assert section.name == "Alpha" and section.messages[0].id == "1"
    text = as_text([section])
    assert "Alpha <a@gmail.com> - 1 unread" in text and "Subject 1" in text
    assert "poppee run" in as_text([])


def test_corrupt_state_is_ignored(tmp_path):
    (tmp_path / "state.json").write_text("{not json")
    assert load_sections(tmp_path / "state.json") == []


def test_state_ui_thread_safe_persistence(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)

    def writer(i: int) -> None:
        state.set_ui("position", {"x": i, "y": i * 2})
        state.set_ui("compact_dock", bool(i % 2))

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(writer, range(24)))

    reloaded = State(path)
    pos = reloaded.get_ui("position")
    assert isinstance(pos, dict) and "x" in pos and "y" in pos
    assert isinstance(reloaded.get_ui("compact_dock"), bool)


def test_demo_checker_supports_unread_recent_and_mark_as_read():
    checker, _ = build_demo_checker()
    results = checker.check_all()
    assert len(results) == 2
    total_before = sum(r.unread for r in results)
    assert total_before == 3
    assert all(len(r.inbox_recent) >= len(r.recent) for r in results)

    first_account = results[0].account.email
    first_msg = results[0].recent[0].id
    updated = checker.mark_as_read(first_account, first_msg)
    assert sum(r.unread for r in updated) == total_before - 1


def test_query_builder_and_parser_roundtrip():
    q = build_query(
        FilterSpec(
            senders=["alerts@github.com", "billing@stripe.com"],
            category="updates",
            label="Financeiro 2026",
            in_inbox=True,
            unread_only=True,
            extra="has:attachment",
        )
    )
    assert q == (
        "is:unread in:inbox (from:alerts@github.com OR from:billing@stripe.com) "
        'category:updates label:"Financeiro 2026" has:attachment'
    )
    parsed = parse_query(q)
    assert parsed.senders == ["alerts@github.com", "billing@stripe.com"]
    assert parsed.category == "updates"
    assert parsed.label == "Financeiro 2026"
    assert parsed.in_inbox is True
    assert parsed.unread_only is True
    assert parsed.extra == "has:attachment"

    simple = parse_query("is:unread from:boss@co.com label:vip")
    assert simple.senders == ["boss@co.com"]
    assert simple.label == "vip"
    assert simple.in_inbox is False
    assert build_query(simple) == "is:unread from:boss@co.com label:vip"
