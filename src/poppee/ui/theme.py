"""Visual design tokens, dark QSS stylesheet, and crisp vector icons for PySide6."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

# Color palette (modern dark desktop overlay matching the prototype)
BG_BUBBLE = QColor(18, 22, 31, 242)
BG_BUBBLE_HOVER = QColor(24, 30, 42, 250)
BORDER_BUBBLE = QColor(255, 255, 255, 28)
BORDER_BUBBLE_HOVER = QColor(255, 255, 255, 56)
BORDER_PINNED = QColor(96, 165, 250, 150)
BORDER_ERROR = QColor(245, 158, 11, 170)

BG_PANEL = QColor(19, 23, 33, 246)
BORDER_PANEL = QColor(255, 255, 255, 26)

BADGE_BG = QColor(96, 26, 36, 245)
BADGE_RING = QColor(220, 68, 83, 120)
BADGE_TEXT = QColor(255, 110, 122)

ACCENT_BLUE = QColor(96, 165, 250)
ICON_WHITE = QColor(241, 245, 249)
ICON_MUTED = QColor(148, 163, 184)

FONT_FAMILY = '"Segoe UI Variable", "Segoe UI", "Inter", sans-serif'

PANEL_STYLESHEET = f"""
QWidget#PreviewRoot {{
    background: transparent;
    font-family: {FONT_FAMILY};
    color: #F1F5F9;
}}

QLabel {{
    background: transparent;
    color: #F1F5F9;
}}

QPushButton#SegBtn {{
    background: transparent;
    color: #94A3B8;
    border: none;
    border-radius: 7px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#SegBtn:hover {{
    color: #E2E8F0;
    background: rgba(255, 255, 255, 0.05);
}}
QPushButton#SegBtn[active="true"] {{
    background: rgba(255, 255, 255, 0.11);
    color: #F8FAFC;
    font-weight: 600;
}}

QPushButton#IconBtn {{
    background: transparent;
    color: #94A3B8;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 4px;
    font-size: 13px;
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
}}
QPushButton#IconBtn:hover {{
    background: rgba(255, 255, 255, 0.08);
    color: #F8FAFC;
}}
QPushButton#IconBtn[active="true"] {{
    background: rgba(96, 165, 250, 0.18);
    border: 1px solid rgba(96, 165, 250, 0.45);
    color: #93C5FD;
}}

QPushButton#AccountPill {{
    background: rgba(255, 255, 255, 0.04);
    color: #94A3B8;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 500;
}}
QPushButton#AccountPill:hover {{
    background: rgba(255, 255, 255, 0.09);
    color: #E2E8F0;
}}
QPushButton#AccountPill[active="true"] {{
    background: rgba(96, 165, 250, 0.18);
    border: 1px solid rgba(96, 165, 250, 0.45);
    color: #DBEAFE;
    font-weight: 600;
}}

QScrollArea#MessageScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#MessageScroll > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 4px 1px 4px 1px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.16);
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 0.28);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QFrame#MessageCard {{
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.04);
    border-radius: 10px;
}}
QFrame#MessageCard:hover {{
    background: rgba(255, 255, 255, 0.075);
    border: 1px solid rgba(255, 255, 255, 0.10);
}}

QPushButton#MarkReadBtn {{
    background: rgba(255, 255, 255, 0.07);
    color: #CBD5E1;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    padding: 0px;
    min-width: 22px;
    max-width: 22px;
    min-height: 20px;
    max-height: 20px;
}}
QPushButton#MarkReadBtn:hover {{
    background: rgba(34, 197, 94, 0.22);
    border: 1px solid rgba(34, 197, 94, 0.50);
    color: #86EFAC;
}}

QPushButton#LinkBtn {{
    background: transparent;
    color: #93C5FD;
    border: none;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 4px;
}}
QPushButton#LinkBtn:hover {{
    color: #BFDBFE;
    text-decoration: underline;
}}

QFrame#ErrorBanner {{
    background: rgba(239, 68, 68, 0.12);
    border: 1px solid rgba(239, 68, 68, 0.28);
    border-radius: 8px;
}}

QPushButton#OtpCopyBtn {{
    background: rgba(16, 185, 129, 0.16);
    color: #6EE7B7;
    border: 1px solid rgba(16, 185, 129, 0.42);
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#OtpCopyBtn:hover {{
    background: rgba(16, 185, 129, 0.28);
    color: #A7F3D0;
}}

QFrame#OtpBanner {{
    background: rgba(16, 185, 129, 0.13);
    border: 1px solid rgba(16, 185, 129, 0.36);
    border-radius: 9px;
}}

QPushButton#BackBtn {{
    background: rgba(255, 255, 255, 0.06);
    color: #E2E8F0;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#BackBtn:hover {{
    background: rgba(255, 255, 255, 0.12);
    color: #FFFFFF;
}}
QPushButton#BackBtn:disabled {{
    background: rgba(255, 255, 255, 0.025);
    color: #475569;
    border: 1px solid rgba(255, 255, 255, 0.04);
}}

QTextBrowser#BodyViewer {{
    background: rgba(15, 19, 27, 0.85);
    color: #E2E8F0;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 10px;
    padding: 8px 10px;
    font-family: {FONT_FAMILY};
    font-size: 12px;
    selection-background-color: rgba(96, 165, 250, 0.35);
}}

QMenu {{
    background-color: #161B26;
    color: #E2E8F0;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 5px;
    font-family: {FONT_FAMILY};
    font-size: 12px;
}}
QMenu::item {{
    padding: 6px 20px 6px 12px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: rgba(96, 165, 250, 0.20);
    color: #F8FAFC;
}}
QMenu::separator {{
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    margin: 4px 8px;
}}
"""


def draw_envelope(painter: QPainter, rect: QRectF, color: QColor, stroke: float = 1.8) -> None:
    """Draw a crisp minimalist outline envelope icon inside ``rect``."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(
        color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
    )
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    radius = min(rect.width(), rect.height()) * 0.18
    painter.drawRoundedRect(rect, radius, radius)

    flap = QPainterPath()
    inset_x = rect.width() * 0.09
    inset_y = rect.height() * 0.14
    flap.moveTo(QPointF(rect.left() + inset_x, rect.top() + inset_y))
    flap.lineTo(QPointF(rect.center().x(), rect.top() + rect.height() * 0.56))
    flap.lineTo(QPointF(rect.right() - inset_x, rect.top() + inset_y))
    painter.drawPath(flap)
    painter.restore()


def make_tray_icon(unread: int = 0, error: bool = False) -> QIcon:
    """Render a crisp vector QIcon for the Windows system tray."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    bg = QColor(18, 22, 31)
    border = BORDER_ERROR if error else QColor(71, 85, 105)
    p.setBrush(bg)
    p.setPen(QPen(border, 2.5))
    p.drawRoundedRect(QRectF(3, 3, size - 6, size - 6), 14, 14)

    env_rect = QRectF(14, 20, 36, 26)
    draw_envelope(p, env_rect, ICON_WHITE if unread > 0 else ICON_MUTED, stroke=3.2)

    if unread > 0:
        badge_r = 24
        badge_rect = QRectF(size - badge_r - 2, 2, badge_r, badge_r)
        p.setBrush(QColor(220, 38, 38))
        p.setPen(QPen(QColor(18, 22, 31), 2.0))
        p.drawEllipse(badge_rect)

        font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        label = "99+" if unread > 99 else str(unread)
        if len(label) >= 3:
            font.setPointSize(8)
            p.setFont(font)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

    p.end()
    return QIcon(pixmap)
