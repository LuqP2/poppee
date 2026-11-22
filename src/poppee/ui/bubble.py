"""Frameless always-on-top floating pill ("chat head") widget."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QApplication, QWidget

from . import theme
from .layout_math import (
    DockEdge,
    Rect,
    clamp_bubble_pos,
    detect_dock_edge,
    docked_bubble_x,
    format_badge,
)


class FloatingBubble(QWidget):
    """Draggable, always-on-top floating pill with envelope icon and unread badge."""

    hover_entered = Signal()
    hover_left = Signal()
    clicked = Signal()
    drag_started = Signal()
    position_committed = Signal(int, int, object)  # x, y, dock_edge
    context_menu_requested = Signal(QPoint)

    IDLE_ZERO_OPACITY = 0.50
    ACTIVE_OPACITY = 1.0
    PILL_HEIGHT = 44
    PILL_WIDTH_EMPTY = 48
    PILL_WIDTH_BADGE = 80
    PILL_WIDTH_WIDE_BADGE = 88

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._unread = 0
        self._more = False
        self._has_error = False
        self._checking = False
        self._hovered = False
        self._pinned = False
        self._compact_dock = True
        self._dock_edge: DockEdge = None
        self._scale = 1.0

        # Drag state
        self._press_global: QPoint | None = None
        self._drag_offset: QPoint | None = None
        self._dragging = False

        # Animations
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_anim.setDuration(180)
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(200)
        self._pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setFixedSize(self.PILL_WIDTH_EMPTY, self.PILL_HEIGHT)
        self.setWindowOpacity(self.IDLE_ZERO_OPACITY)

    # State setters ------------------------------------------------------------

    @property
    def dock_edge(self) -> DockEdge:
        return self._dock_edge

    @property
    def compact_dock(self) -> bool:
        return self._compact_dock

    @property
    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float) -> None:
        clamped = max(0.8, min(1.8, float(scale)))
        if abs(self._scale - clamped) < 0.005:
            return
        self._scale = clamped
        self._apply_dimensions()
        self.update()

    def _scaled(self, px: float) -> int:
        return max(1, round(px * self._scale))

    def _apply_dimensions(self) -> None:
        old_w = self.width()
        badge = format_badge(self._unread, self._more)
        if not badge:
            base_w = self.PILL_WIDTH_EMPTY
        elif len(badge) >= 3:
            base_w = self.PILL_WIDTH_WIDE_BADGE
        else:
            base_w = self.PILL_WIDTH_BADGE

        target_w = self._scaled(base_w)
        target_h = self._scaled(self.PILL_HEIGHT)
        if target_w == old_w and target_h == self.height():
            return

        screen = self._screen_rect()
        old_right = self.x() + old_w
        self.setFixedSize(target_w, target_h)
        if self._dock_edge == "right" or (self.x() + old_w // 2 >= screen.center_x):
            self.move(old_right - target_w, self.y())
        cx, cy = clamp_bubble_pos(self.x(), self.y(), target_w, target_h, screen, margin=6)
        self.move(cx, cy)
        self._sync_dock_position(animate=False)

    def set_compact_dock(self, enabled: bool) -> None:
        self._compact_dock = enabled
        if not enabled:
            self._dock_edge = None
            screen = self._screen_rect()
            cx, cy = clamp_bubble_pos(self.x(), self.y(), self.width(), self.height(), screen)
            self._animate_pos(QPoint(cx, cy))
        else:
            screen = self._screen_rect()
            self._dock_edge = detect_dock_edge(self.x(), self.width(), screen)
            self._sync_dock_position(animate=True)

    def set_dock_edge(self, edge: DockEdge) -> None:
        self._dock_edge = edge if self._compact_dock else None

    def set_counts(self, unread: int, *, more: bool = False, has_error: bool = False) -> None:
        self._unread = max(0, unread)
        self._more = more
        self._has_error = has_error
        self._apply_dimensions()
        self._sync_opacity(animate=True)
        self.update()

    def set_checking(self, checking: bool) -> None:
        self._checking = checking
        self.update()

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._sync_opacity(animate=True)
        self._sync_dock_position(animate=True)
        self.update()

    def set_panel_open(self, is_open: bool) -> None:
        self._hovered = is_open or self.underMouse()
        self._sync_opacity(animate=True)
        self._sync_dock_position(animate=True)
        self.update()

    def expanded_geometry_rect(self) -> Rect:
        """Return bubble rect in its expanded (non-peeking) position for panel anchoring."""
        screen = self._screen_rect()
        x = self.x()
        if self._compact_dock and self._dock_edge is not None:
            x = docked_bubble_x(self._dock_edge, self.x(), self.width(), screen, expanded=True)
        return Rect(x, self.y(), self.width(), self.height())

    # Screen & animations ------------------------------------------------------

    def _screen_rect(self) -> Rect:
        screen = self.screen() or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        return Rect(geo.x(), geo.y(), geo.width(), geo.height())

    def _sync_opacity(self, *, animate: bool = True) -> None:
        target = (
            self.ACTIVE_OPACITY
            if (self._unread > 0 or self._hovered or self._pinned or self._has_error)
            else self.IDLE_ZERO_OPACITY
        )
        if abs(self.windowOpacity() - target) < 0.01:
            return
        if not animate:
            self._opacity_anim.stop()
            self.setWindowOpacity(target)
            return
        self._opacity_anim.stop()
        self._opacity_anim.setStartValue(self.windowOpacity())
        self._opacity_anim.setEndValue(target)
        self._opacity_anim.start()

    def _sync_dock_position(self, *, animate: bool = True) -> None:
        if self._dragging or not self._compact_dock or self._dock_edge is None:
            return
        screen = self._screen_rect()
        expanded = self._hovered or self._pinned
        peek = self._scaled(28 if self._unread > 0 else 20)
        target_x = docked_bubble_x(
            self._dock_edge,
            self.x(),
            self.width(),
            screen,
            peek=peek,
            expanded=expanded,
        )
        target = QPoint(target_x, self.y())
        if target == self.pos():
            return
        if animate:
            self._animate_pos(target)
        else:
            self._pos_anim.stop()
            self.move(target)

    def _animate_pos(self, target: QPoint) -> None:
        self._pos_anim.stop()
        self._pos_anim.setStartValue(self.pos())
        self._pos_anim.setEndValue(target)
        self._pos_anim.start()

    # Mouse & hover events -----------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._sync_opacity(animate=True)
        self._sync_dock_position(animate=True)
        self.update()
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._sync_opacity(animate=True)
        self._sync_dock_position(animate=True)
        self.update()
        self.hover_left.emit()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pos_anim.stop()
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.frameGeometry().topLeft()
            self._dragging = False
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_global is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            current = event.globalPosition().toPoint()
            if not self._dragging:
                dist = (current - self._press_global).manhattanLength()
                if dist >= QApplication.startDragDistance():
                    self._dragging = True
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    self.drag_started.emit()
            if self._dragging and self._drag_offset is not None:
                self.move(current - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            self._press_global = None
            self._drag_offset = None
            self._dragging = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)

            if was_dragging:
                screen = self._screen_rect()
                cx, cy = clamp_bubble_pos(
                    self.x(), self.y(), self.width(), self.height(), screen, margin=6
                )
                self.move(cx, cy)
                self._dock_edge = (
                    detect_dock_edge(cx, self.width(), screen) if self._compact_dock else None
                )
                self.position_committed.emit(cx, cy, self._dock_edge)
                self._sync_dock_position(animate=True)
            else:
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # Painting -----------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        s = self._scale
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        radius = 14.0 * s

        # Background pill
        bg = theme.BG_BUBBLE_HOVER if (self._hovered or self._pinned) else theme.BG_BUBBLE
        if self._has_error:
            border = theme.BORDER_ERROR
        elif self._pinned:
            border = theme.BORDER_PINNED
        elif self._hovered:
            border = theme.BORDER_BUBBLE_HOVER
        else:
            border = theme.BORDER_BUBBLE

        p.setBrush(bg)
        p.setPen(QPen(border, max(1.1, 1.2 * s)))
        p.drawRoundedRect(rect, radius, radius)

        badge = format_badge(self._unread, self._more)
        env_w, env_h = 20.0 * s, 15.0 * s
        env_y = (self.height() - env_h) / 2.0
        stroke = max(1.6, 1.8 * s)

        if badge:
            env_x = 14.0 * s
            theme.draw_envelope(
                p, QRectF(env_x, env_y, env_w, env_h), theme.ICON_WHITE, stroke=stroke
            )

            # Circular/pill crimson badge on the right
            badge_h = 24.0 * s
            badge_w = (24.0 if len(badge) == 1 else (28.0 if len(badge) == 2 else 34.0)) * s
            badge_x = self.width() - badge_w - 10.0 * s
            badge_y = (self.height() - badge_h) / 2.0
            badge_rect = QRectF(badge_x, badge_y, badge_w, badge_h)

            p.setBrush(theme.BADGE_BG)
            p.setPen(QPen(theme.BADGE_RING, max(1.0, 1.0 * s)))
            p.drawRoundedRect(badge_rect, badge_h / 2.0, badge_h / 2.0)

            base_pt = 10.0 if len(badge) <= 2 else 8.0
            font = QFont("Segoe UI Variable", max(7, round(base_pt * s)), QFont.Weight.DemiBold)
            p.setFont(font)
            p.setPen(theme.BADGE_TEXT)
            p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
        else:
            env_x = (self.width() - env_w) / 2.0
            icon_color = theme.ICON_WHITE if (self._hovered or self._pinned) else theme.ICON_MUTED
            theme.draw_envelope(p, QRectF(env_x, env_y, env_w, env_h), icon_color, stroke=stroke)

        # Subtle status dot (checking = blue dot top-right, pinned = small blue dot top-left)
        dot_d = 4.5 * s
        if self._checking:
            p.setBrush(theme.ACCENT_BLUE)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(self.width() - 9.0 * s, 5.0 * s, dot_d, dot_d))
        elif self._pinned:
            p.setBrush(theme.ACCENT_BLUE)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(6.0 * s, 6.0 * s, dot_d, dot_d))

        # Subtle edge grip hint when docked & peeking
        if self._compact_dock and self._dock_edge and not (self._hovered or self._pinned):
            p.setBrush(QColor(255, 255, 255, 55))
            p.setPen(Qt.PenStyle.NoPen)
            grip_w = 2.5 * s
            grip_h = 14.0 * s
            grip_x = 4.0 * s if self._dock_edge == "right" else self.width() - 6.5 * s
            p.drawRoundedRect(
                QRectF(grip_x, (self.height() - grip_h) / 2.0, grip_w, grip_h),
                grip_w / 2.0,
                grip_w / 2.0,
            )

        p.end()
