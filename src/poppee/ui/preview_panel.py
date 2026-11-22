"""Frameless, edge-resizable dark inbox preview panel anchored to the floating bubble."""

from __future__ import annotations

import time
from typing import Literal

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QFontMetrics, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..checker import AccountResult
from ..gmail import Message, inbox_url
from ..preview import format_age
from ..util import open_url
from . import theme

ViewMode = Literal["unread", "recent"]


class ElidedLabel(QLabel):
    """Single-line label that dynamically elides text to its live width on resize."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(20)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self.update()

    def text(self) -> str:
        return self._full_text

    def sizeHint(self):  # noqa: N802
        fm = QFontMetrics(self.font())
        return super().sizeHint().expandedTo(fm.boundingRect(self._full_text[:24]).size())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width()))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        p.end()


class MessageCard(QFrame):
    """Single email preview card with click-to-open and hover mark-as-read button."""

    mark_read_clicked = Signal(str, str)  # account_email, message_id
    opened = Signal(str)  # url

    def __init__(
        self,
        account_email: str,
        account_name: str,
        message: Message,
        *,
        show_account_tag: bool,
        show_unread_dot: bool,
        now: float,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.account_email = account_email
        self.message = message
        self.setObjectName("MessageCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        # Row 1: unread dot + sender + account tag + age + mark-as-read button
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        if show_unread_dot and message.unread:
            dot = QLabel("●")
            dot.setStyleSheet("color: #60A5FA; font-size: 8px;")
            dot.setFixedWidth(10)
            top.addWidget(dot)

        sender_lbl = ElidedLabel(message.sender)
        sender_lbl.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #F8FAFC;"
            if message.unread
            else "font-size: 12px; font-weight: 500; color: #CBD5E1;"
        )
        top.addWidget(sender_lbl, 1)

        if show_account_tag:
            tag = QLabel(account_name[:18])
            tag.setStyleSheet(
                "font-size: 10px; color: #94A3B8; background: rgba(255,255,255,0.06);"
                "border-radius: 4px; padding: 1px 5px;"
            )
            top.addWidget(tag)

        age_lbl = QLabel(format_age(message.timestamp, now))
        age_lbl.setStyleSheet("font-size: 11px; color: #64748B;")
        top.addWidget(age_lbl)

        self._mark_btn: QPushButton | None = None
        if message.unread:
            btn = QPushButton("✓")
            btn.setObjectName("MarkReadBtn")
            btn.setToolTip("Marcar como lida")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setVisible(False)
            btn.clicked.connect(self._on_mark_read)
            top.addWidget(btn)
            self._mark_btn = btn

        root.addLayout(top)

        # Row 2: subject
        subj_lbl = ElidedLabel(message.subject)
        subj_lbl.setStyleSheet(
            "font-size: 12px; font-weight: 500; color: #E2E8F0;"
            if message.unread
            else "font-size: 12px; font-weight: 400; color: #94A3B8;"
        )
        root.addWidget(subj_lbl)

        # Row 3: snippet
        if message.snippet:
            snip_lbl = ElidedLabel(message.snippet)
            snip_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
            root.addWidget(snip_lbl)

    def _on_mark_read(self) -> None:
        if self._mark_btn is not None:
            self._mark_btn.setEnabled(False)
            self._mark_btn.setText("…")
        self.mark_read_clicked.emit(self.account_email, self.message.id)

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._mark_btn is not None:
            self._mark_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._mark_btn is not None:
            self._mark_btn.setVisible(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            url = self.message.url(self.account_email)
            open_url(url)
            self.opened.emit(url)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PreviewPanel(QWidget):
    """Floating dark inbox preview popover resizable from all edges and corners."""

    hover_entered = Signal()
    hover_left = Signal()
    refresh_requested = Signal()
    pin_toggled = Signal()
    settings_requested = Signal()
    view_mode_changed = Signal(str)
    mark_read_requested = Signal(str, str)  # account_email, message_id
    message_opened = Signal()
    size_committed = Signal(int, int)  # width, height

    DEFAULT_WIDTH = 400
    DEFAULT_HEIGHT = 440
    MIN_WIDTH = 300
    MIN_HEIGHT = 220
    MAX_WIDTH = 820
    MAX_HEIGHT = 860
    RESIZE_MARGIN = 7

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PreviewRoot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setStyleSheet(theme.PANEL_STYLESHEET)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.setMaximumSize(self.MAX_WIDTH, self.MAX_HEIGHT)

        self._results: list[AccountResult] = []
        self._view_mode: ViewMode = "unread"
        self._selected_account: str | None = None  # None = all accounts
        self._pinned = False
        self._checking = False
        self._last_updated: str = ""
        self._status_override: str = ""
        self._demo_mode = False

        # Edge-resize state
        self._resize_edges: str = ""
        self._resize_origin_global: QPoint | None = None
        self._resize_origin_geo: QRect | None = None
        self._has_custom_size = False

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(150)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._hiding = False

        self._build_ui()
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 11, 12, 10)
        outer.setSpacing(8)

        # Header: segmented toggle (Não lidas | Recentes) + action buttons
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        seg_box = QFrame()
        seg_box.setStyleSheet(
            "background: rgba(255, 255, 255, 0.04); border-radius: 9px; padding: 2px;"
        )
        seg_layout = QHBoxLayout(seg_box)
        seg_layout.setContentsMargins(2, 2, 2, 2)
        seg_layout.setSpacing(2)

        self._btn_unread = QPushButton("Não lidas")
        self._btn_unread.setObjectName("SegBtn")
        self._btn_unread.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_unread.clicked.connect(lambda: self.set_view_mode("unread"))
        seg_layout.addWidget(self._btn_unread)

        self._btn_recent = QPushButton("Recentes")
        self._btn_recent.setObjectName("SegBtn")
        self._btn_recent.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_recent.clicked.connect(lambda: self.set_view_mode("recent"))
        seg_layout.addWidget(self._btn_recent)

        header.addWidget(seg_box)
        header.addStretch(1)

        self._demo_badge = QLabel("DEMO")
        self._demo_badge.setFixedHeight(18)
        self._demo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._demo_badge.setStyleSheet(
            "font-size: 9px; font-weight: 700; color: #FDE68A;"
            "background: rgba(245, 158, 11, 0.18); border: 1px solid rgba(245, 158, 11, 0.38);"
            "border-radius: 5px; padding: 0px 6px;"
        )
        self._demo_badge.setVisible(False)
        header.addWidget(self._demo_badge)

        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setObjectName("IconBtn")
        self._btn_refresh.setToolTip("Verificar agora")
        self._btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self._btn_refresh)

        self._btn_pin = QPushButton("📌")
        self._btn_pin.setObjectName("IconBtn")
        self._btn_pin.setToolTip("Fixar painel")
        self._btn_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_pin.clicked.connect(self.pin_toggled.emit)
        header.addWidget(self._btn_pin)

        self._btn_settings = QPushButton("⚙")
        self._btn_settings.setObjectName("IconBtn")
        self._btn_settings.setToolTip("Configurações")
        self._btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_settings.clicked.connect(self.settings_requested.emit)
        header.addWidget(self._btn_settings)

        outer.addLayout(header)

        # Account filter bar (visible when 2+ accounts)
        self._accounts_bar = QWidget()
        self._accounts_layout = QHBoxLayout(self._accounts_bar)
        self._accounts_layout.setContentsMargins(0, 0, 0, 0)
        self._accounts_layout.setSpacing(6)
        self._accounts_bar.setVisible(False)
        outer.addWidget(self._accounts_bar)

        # Scrollable message list
        self._scroll = QScrollArea()
        self._scroll.setObjectName("MessageScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 2, 0)
        self._list_layout.setSpacing(6)
        self._scroll.setWidget(self._list_host)
        outer.addWidget(self._scroll, 1)

        # Footer
        footer = QHBoxLayout()
        footer.setContentsMargins(2, 2, 2, 0)
        footer.setSpacing(8)

        self._status_lbl = QLabel("Aguardando verificação…")
        self._status_lbl.setStyleSheet("font-size: 11px; color: #64748B;")
        footer.addWidget(self._status_lbl, 1)

        self._open_inbox_btn = QPushButton("Abrir Gmail ↗")
        self._open_inbox_btn.setObjectName("LinkBtn")
        self._open_inbox_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_inbox_btn.clicked.connect(self._open_selected_inbox)
        footer.addWidget(self._open_inbox_btn)

        outer.addLayout(footer)
        self._sync_toggle_styles()

    # Public API ---------------------------------------------------------------

    @property
    def is_resizing(self) -> bool:
        return bool(self._resize_edges and self._resize_origin_global is not None)

    def set_custom_size(self, width: int, height: int) -> None:
        w = max(self.MIN_WIDTH, min(self.MAX_WIDTH, int(width)))
        h = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, int(height)))
        self._has_custom_size = True
        self.resize(w, h)

    def reset_size(self) -> None:
        self._has_custom_size = False
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def set_demo_mode(self, enabled: bool) -> None:
        self._demo_mode = enabled
        self._demo_badge.setVisible(enabled)

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._btn_pin.setProperty("active", pinned)
        self._btn_pin.setToolTip("Desafixar painel" if pinned else "Fixar painel")
        self._btn_pin.style().unpolish(self._btn_pin)
        self._btn_pin.style().polish(self._btn_pin)
        self.update()

    def set_view_mode(self, mode: ViewMode, *, emit: bool = True) -> None:
        if mode not in ("unread", "recent"):
            mode = "unread"
        if self._view_mode == mode:
            self._sync_toggle_styles()
            return
        self._view_mode = mode
        self._sync_toggle_styles()
        self._render()
        if emit:
            self.view_mode_changed.emit(mode)

    def set_checking(self, checking: bool) -> None:
        self._checking = checking
        self._btn_refresh.setEnabled(not checking)
        self._update_status_text()

    def set_status_feedback(self, message: str) -> None:
        self._status_override = message
        self._update_status_text()

    def set_results(self, results: list[AccountResult]) -> None:
        self._results = list(results)
        self._last_updated = time.strftime("%H:%M")
        self._status_override = ""
        if self._selected_account and not any(
            r.account.key == self._selected_account for r in self._results
        ):
            self._selected_account = None
        self._render()

    def show_animated(self, x: int, y: int) -> None:
        self._hiding = False
        self._fade_anim.stop()
        self.move(x, y)
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
        self.raise_()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def hide_animated(self) -> None:
        if not self.isVisible() or self._hiding:
            return
        self._hiding = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def desired_height(self) -> int:
        if self._has_custom_size:
            return self.height()
        return self.DEFAULT_HEIGHT

    # Edge-resize helpers ------------------------------------------------------

    def _hit_test_edges(self, pos: QPoint) -> str:
        m = self.RESIZE_MARGIN
        edges = ""
        if pos.y() <= m:
            edges += "T"
        elif pos.y() >= self.height() - m:
            edges += "B"
        if pos.x() <= m:
            edges += "L"
        elif pos.x() >= self.width() - m:
            edges += "R"
        return edges

    def _cursor_for_edges(self, edges: str) -> Qt.CursorShape:
        if edges in ("TL", "BR"):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in ("TR", "BL"):
            return Qt.CursorShape.SizeBDiagCursor
        if edges in ("L", "R"):
            return Qt.CursorShape.SizeHorCursor
        if edges in ("T", "B"):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._hit_test_edges(event.position().toPoint())
            if edges:
                self._resize_edges = edges
                self._resize_origin_global = event.globalPosition().toPoint()
                self._resize_origin_geo = QRect(self.geometry())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._resize_edges
            and self._resize_origin_global is not None
            and self._resize_origin_geo is not None
        ):
            delta = event.globalPosition().toPoint() - self._resize_origin_global
            geo = QRect(self._resize_origin_geo)

            if "R" in self._resize_edges:
                new_w = max(self.MIN_WIDTH, min(self.MAX_WIDTH, geo.width() + delta.x()))
                geo.setWidth(new_w)
            elif "L" in self._resize_edges:
                new_w = max(self.MIN_WIDTH, min(self.MAX_WIDTH, geo.width() - delta.x()))
                geo.setLeft(geo.right() - new_w + 1)

            if "B" in self._resize_edges:
                new_h = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, geo.height() + delta.y()))
                geo.setHeight(new_h)
            elif "T" in self._resize_edges:
                new_h = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, geo.height() - delta.y()))
                geo.setTop(geo.bottom() - new_h + 1)

            self.setGeometry(geo)
            self._has_custom_size = True
            event.accept()
            return

        edges = self._hit_test_edges(event.position().toPoint())
        self.setCursor(self._cursor_for_edges(edges))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._resize_edges:
            self._resize_edges = ""
            self._resize_origin_global = None
            self._resize_origin_geo = None
            self.size_committed.emit(self.width(), self.height())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # Internal rendering -------------------------------------------------------

    def _on_fade_finished(self) -> None:
        if self._hiding:
            self._hiding = False
            self.hide()

    def _sync_toggle_styles(self) -> None:
        for btn, active in (
            (self._btn_unread, self._view_mode == "unread"),
            (self._btn_recent, self._view_mode == "recent"),
        ):
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_status_text(self) -> None:
        if self._status_override:
            self._status_lbl.setText(self._status_override)
        elif self._checking:
            self._status_lbl.setText("Verificando mensagens…")
        elif self._last_updated:
            total = sum(r.unread for r in self._results)
            label = "1 não lida" if total == 1 else f"{total} não lidas"
            self._status_lbl.setText(f"{label} · {self._last_updated}")
        else:
            self._status_lbl.setText("Pronto")

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _select_account(self, account_key: str | None) -> None:
        self._selected_account = account_key
        self._render()

    def _open_selected_inbox(self) -> None:
        target = None
        if self._selected_account:
            target = next(
                (r.account.email for r in self._results if r.account.key == self._selected_account),
                None,
            )
        elif self._results:
            target = self._results[0].account.email
        open_url(inbox_url(target) if target else "https://mail.google.com/")
        self.message_opened.emit()

    def _render(self) -> None:
        self._clear_layout(self._accounts_layout)
        self._clear_layout(self._list_layout)

        # Account filter pills when multiple accounts exist
        multi = len(self._results) > 1
        self._accounts_bar.setVisible(multi)
        if multi:
            total = sum(r.unread for r in self._results)
            all_btn = QPushButton(f"Todas ({total})" if total else "Todas")
            all_btn.setObjectName("AccountPill")
            all_btn.setProperty("active", self._selected_account is None)
            all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            all_btn.clicked.connect(lambda: self._select_account(None))
            self._accounts_layout.addWidget(all_btn)

            for r in self._results:
                suffix = f" ({r.count_label})" if r.unread else ""
                btn = QPushButton(f"{r.account.name}{suffix}")
                btn.setObjectName("AccountPill")
                btn.setProperty("active", self._selected_account == r.account.key)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                key = r.account.key
                btn.clicked.connect(lambda _=False, k=key: self._select_account(k))
                self._accounts_layout.addWidget(btn)
            self._accounts_layout.addStretch(1)

        visible_results = [
            r
            for r in self._results
            if self._selected_account is None or r.account.key == self._selected_account
        ]

        # Error banners
        for r in visible_results:
            if r.error:
                banner = QFrame()
                banner.setObjectName("ErrorBanner")
                bl = QVBoxLayout(banner)
                bl.setContentsMargins(9, 7, 9, 7)
                bl.setSpacing(2)
                t = QLabel(f"⚠ {r.account.name}")
                t.setStyleSheet("font-size: 11px; font-weight: 600; color: #FCA5A5;")
                d = QLabel(r.error)
                d.setWordWrap(True)
                d.setStyleSheet("font-size: 11px; color: #FECACA;")
                bl.addWidget(t)
                bl.addWidget(d)
                self._list_layout.addWidget(banner)

        # Collect messages sorted newest-first across visible accounts
        entries: list[tuple[AccountResult, Message]] = []
        for r in visible_results:
            msgs = r.recent if self._view_mode == "unread" else (r.inbox_recent or r.recent)
            for m in msgs:
                entries.append((r, m))
        entries.sort(key=lambda pair: pair[1].timestamp, reverse=True)

        now = time.time()
        show_tag = multi and self._selected_account is None
        show_dot = self._view_mode == "recent"

        if not self._results:
            self._add_empty_state(
                "Nenhuma conta configurada",
                "Clique em ⚙ no canto superior para conectar sua conta Gmail.",
            )
        elif not entries:
            if self._view_mode == "unread":
                self._add_empty_state(
                    "Tudo em dia",
                    "Nenhuma mensagem não lida no momento.",
                )
            else:
                self._add_empty_state(
                    "Caixa vazia",
                    "Nenhuma mensagem recente encontrada.",
                )
        else:
            for r, m in entries:
                card = MessageCard(
                    r.account.email,
                    r.account.name,
                    m,
                    show_account_tag=show_tag,
                    show_unread_dot=show_dot,
                    now=now,
                )
                card.mark_read_clicked.connect(self.mark_read_requested.emit)
                card.opened.connect(lambda _url: self.message_opened.emit())
                self._list_layout.addWidget(card)

        self._list_layout.addStretch(1)
        self._update_status_text()

    def _add_empty_state(self, title: str, subtitle: str) -> None:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 26, 16, 26)
        lay.setSpacing(4)
        t = QLabel(title)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("font-size: 13px; font-weight: 600; color: #E2E8F0;")
        s = QLabel(subtitle)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setWordWrap(True)
        s.setStyleSheet("font-size: 11px; color: #64748B;")
        lay.addWidget(t)
        lay.addWidget(s)
        self._list_layout.addWidget(box)

    # Events & painting --------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self.is_resizing:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.hover_left.emit()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._pinned:
            self.pin_toggled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        border = theme.BORDER_PINNED if self._pinned else theme.BORDER_PANEL
        p.setBrush(theme.BG_PANEL)
        p.setPen(QPen(border, 1.1))
        p.drawRoundedRect(rect, 14.0, 14.0)
        p.end()
