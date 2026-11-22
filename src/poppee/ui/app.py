"""Application controller coordinating FloatingBubble, PreviewPanel, QSystemTrayIcon and Checker."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from .. import APP_NAME, config
from ..checker import AccountResult, Checker
from ..gmail import inbox_url
from ..notify import Notification
from ..util import open_path, open_url
from .layout_math import (
    DockEdge,
    Rect,
    clamp_bubble_pos,
    compute_panel_pos,
    default_bubble_pos,
    detect_dock_edge,
)

log = logging.getLogger(__name__)


class UiUnavailable(Exception):
    """Raised when PySide6 / a graphical display is not available."""


def total_unread(results: list[AccountResult]) -> int:
    return sum(r.unread for r in results)


def tray_tooltip(results: list[AccountResult]) -> str:
    total = total_unread(results)
    errors = sum(1 for r in results if r.error)
    text = f"{APP_NAME}: {total} não lida(s)" if results else f"{APP_NAME}: sem contas"
    if errors:
        text += f", {errors} com erro"
    return text[:63]


class WidgetApp:
    """Runs the Qt event loop, floating chat-head widget, tray icon, and background poller."""

    EXPAND_DELAY_MS = 140
    COLLAPSE_DELAY_MS = 280

    def __init__(self, checker: Checker, config_path: Path, *, demo: bool = False):
        self.checker = checker
        self.config_path = config_path
        self.demo = demo
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._results: list[AccountResult] = []
        self._pinned = False
        self._settings_open = False

    def run(self) -> None:
        try:
            from PySide6.QtCore import QObject, QTimer, Signal
            from PySide6.QtGui import QAction, QCursor
            from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
        except Exception as e:
            raise UiUnavailable(str(e)) from e

        from . import theme
        from .bubble import FloatingBubble
        from .preview_panel import PreviewPanel

        class _Bridge(QObject):
            results_ready = Signal(list)
            checking_changed = Signal(bool)
            status_message = Signal(str)
            body_ready = Signal(
                str, str, object, object
            )  # email, msg_id, MessageBody|None, err|None

        app = QApplication.instance() or QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName(APP_NAME)
        self._app = app
        self._bridge = _Bridge()
        self._qcursor = QCursor
        self._qmenu_cls = QMenu
        self._qaction_cls = QAction
        self._theme = theme

        # Widgets
        self._bubble = FloatingBubble()
        self._panel = PreviewPanel()
        self._panel.set_demo_mode(self.demo)

        # Restore persisted UI preferences from thread-safe State
        saved_scale = self.checker.state.get_ui("bubble_scale", 1.0)
        if isinstance(saved_scale, (int, float)):
            self._bubble.set_scale(float(saved_scale))
        compact = self.checker.state.get_ui("compact_dock", True)
        self._bubble.set_compact_dock(bool(compact))
        saved_mode = self.checker.state.get_ui("view_mode", "unread")
        self._panel.set_view_mode(saved_mode, emit=False)
        saved_panel_size = self.checker.state.get_ui("panel_size")
        if (
            isinstance(saved_panel_size, dict)
            and isinstance(saved_panel_size.get("w"), int)
            and isinstance(saved_panel_size.get("h"), int)
        ):
            self._panel.set_custom_size(saved_panel_size["w"], saved_panel_size["h"])
        self._restore_bubble_position()

        # Timers for smooth hover expand/collapse
        self._expand_timer = QTimer()
        self._expand_timer.setSingleShot(True)
        self._expand_timer.setInterval(self.EXPAND_DELAY_MS)
        self._expand_timer.timeout.connect(self._open_panel)

        self._collapse_timer = QTimer()
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(self.COLLAPSE_DELAY_MS)
        self._collapse_timer.timeout.connect(self._maybe_collapse_panel)

        # Wire bubble <-> panel signals
        self._bubble.hover_entered.connect(self._on_bubble_hover_enter)
        self._bubble.hover_left.connect(self._on_hover_leave)
        self._bubble.drag_started.connect(self._on_drag_started)
        self._bubble.clicked.connect(self._toggle_pin)
        self._bubble.position_committed.connect(self._on_position_committed)
        self._bubble.context_menu_requested.connect(self._show_context_menu)

        self._panel.hover_entered.connect(self._on_panel_hover_enter)
        self._panel.hover_left.connect(self._on_hover_leave)
        self._panel.refresh_requested.connect(self._check_now)
        self._panel.pin_toggled.connect(self._toggle_pin)
        self._panel.settings_requested.connect(self._open_settings)
        self._panel.view_mode_changed.connect(self._on_view_mode_changed)
        self._panel.mark_read_requested.connect(self._on_mark_read_requested)
        self._panel.message_selected.connect(self._on_message_selected)
        self._panel.code_copied.connect(self._on_code_copied)
        self._panel.message_opened.connect(self._on_message_opened)
        self._panel.size_committed.connect(self._on_panel_size_committed)

        # Wire background worker signals
        self._bridge.results_ready.connect(self._on_results)
        self._bridge.checking_changed.connect(self._on_checking_changed)
        self._bridge.status_message.connect(self._panel.set_status_feedback)
        self._bridge.body_ready.connect(self._on_body_ready)

        # System tray icon (native Qt)
        self._tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon(theme.make_tray_icon(0), app)
            tray.setToolTip(APP_NAME)
            tray.activated.connect(self._on_tray_activated)
            tray.setContextMenu(self._build_menu(for_tray=True))
            tray.show()
            self._tray = tray

        self._bubble.show()
        self._bubble.set_panel_open(False)

        # Start polling thread
        threading.Thread(target=self._poll_loop, name="poller", daemon=True).start()
        app.exec()

    # Position & persistence ---------------------------------------------------

    def _screen_rect(self) -> Rect:
        screen = self._bubble.screen() or self._app.primaryScreen()
        geo = screen.availableGeometry()
        return Rect(geo.x(), geo.y(), geo.width(), geo.height())

    def _restore_bubble_position(self) -> None:
        saved = self.checker.state.get_ui("position")
        saved_edge: DockEdge = self.checker.state.get_ui("dock_edge")
        screen = self._screen_rect()
        bw, bh = self._bubble.width(), self._bubble.height()

        if (
            isinstance(saved, dict)
            and isinstance(saved.get("x"), int)
            and isinstance(saved.get("y"), int)
        ):
            x, y = saved["x"], saved["y"]
            # Check against all available screens so multi-monitor positions survive.
            target_screen = screen
            for scr in self._app.screens():
                g = scr.availableGeometry()
                r = Rect(g.x(), g.y(), g.width(), g.height())
                if r.x <= x <= r.right and r.y <= y <= r.bottom:
                    target_screen = r
                    break
            cx, cy = clamp_bubble_pos(x, y, bw, bh, target_screen, margin=6)
            edge = (
                saved_edge
                if saved_edge in ("left", "right")
                else (
                    detect_dock_edge(cx, bw, target_screen) if self._bubble.compact_dock else None
                )
            )
            self._bubble.set_dock_edge(edge)
            self._bubble.move(cx, cy)
        else:
            x, y = default_bubble_pos(bw, bh, screen)
            edge = "right" if self._bubble.compact_dock else None
            self._bubble.set_dock_edge(edge)
            self._bubble.move(x, y)

    def _reset_position(self) -> None:
        screen = self._screen_rect()
        x, y = default_bubble_pos(self._bubble.width(), self._bubble.height(), screen)
        edge: DockEdge = "right" if self._bubble.compact_dock else None
        self._bubble.set_dock_edge(edge)
        self._bubble.move(x, y)
        self._bubble.show()
        self._panel.reset_size()
        self.checker.state.set_ui("panel_size", None, save=False)
        self._on_position_committed(x, y, edge)
        self._bubble.set_panel_open(self._panel.isVisible())

    def _on_position_committed(self, x: int, y: int, edge: DockEdge) -> None:
        self.checker.state.set_ui("position", {"x": x, "y": y}, save=False)
        self.checker.state.set_ui("dock_edge", edge, save=True)

    def _on_panel_size_committed(self, w: int, h: int) -> None:
        self.checker.state.set_ui("panel_size", {"w": w, "h": h}, save=True)

    def _on_view_mode_changed(self, mode: str) -> None:
        self.checker.state.set_ui("view_mode", mode, save=True)
        if self._panel.isVisible():
            self._reposition_panel()

    # Hover, pin & panel visibility --------------------------------------------

    def _on_bubble_hover_enter(self) -> None:
        self._collapse_timer.stop()
        if not self._panel.isVisible():
            self._expand_timer.start()

    def _on_panel_hover_enter(self) -> None:
        self._collapse_timer.stop()
        self._expand_timer.stop()

    def _on_hover_leave(self) -> None:
        self._expand_timer.stop()
        if not self._pinned:
            self._collapse_timer.start()

    def _on_drag_started(self) -> None:
        self._expand_timer.stop()
        self._collapse_timer.stop()
        if self._pinned:
            self._pinned = False
            self._bubble.set_pinned(False)
            self._panel.set_pinned(False)
        self._panel.hide_animated()
        self._bubble.set_panel_open(False)

    def _open_panel(self) -> None:
        self._reposition_panel(show=True)
        self._bubble.set_panel_open(True)

    def _reposition_panel(self, *, show: bool = False) -> None:
        screen = self._screen_rect()
        bubble_rect = self._bubble.expanded_geometry_rect()
        px, py = compute_panel_pos(
            bubble_rect,
            self._panel.width(),
            self._panel.desired_height(),
            screen,
        )
        if show:
            self._panel.show_animated(px, py)
        else:
            self._panel.move(px, py)

    def _maybe_collapse_panel(self) -> None:
        if self._pinned or self._panel.is_resizing:
            return
        cursor = self._qcursor.pos()
        in_bubble = self._bubble.isVisible() and self._bubble.frameGeometry().contains(cursor)
        in_panel = self._panel.isVisible() and self._panel.frameGeometry().contains(cursor)
        if in_bubble or in_panel:
            return
        self._panel.hide_animated()
        self._bubble.set_panel_open(False)

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        self._bubble.set_pinned(self._pinned)
        self._panel.set_pinned(self._pinned)
        if self._pinned:
            self._collapse_timer.stop()
            self._expand_timer.stop()
            self._open_panel()
        else:
            self._panel.hide_animated()
            self._bubble.set_panel_open(False)

    def _on_message_opened(self) -> None:
        if not self._pinned:
            self._panel.hide_animated()
            self._bubble.set_panel_open(False)

    # Background polling & actions ---------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._bridge.checking_changed.emit(True)
            try:
                results = self.checker.check_all()
            except Exception:
                log.exception("Check failed")
                results = self.checker.results
            finally:
                self._bridge.checking_changed.emit(False)
            self._bridge.results_ready.emit(list(results))
            self._wake.wait(self.checker.config.poll_interval)
            self._wake.clear()

    def _on_checking_changed(self, checking: bool) -> None:
        self._bubble.set_checking(checking)
        self._panel.set_checking(checking)

    def _on_results(self, results: list[AccountResult]) -> None:
        self._results = list(results)
        unread = total_unread(results)
        more = any(r.more for r in results)
        all_failed = bool(results) and all(r.error for r in results)

        self._bubble.set_counts(unread, more=more, has_error=all_failed)
        self._panel.set_results(results)
        if self._panel.isVisible():
            self._reposition_panel()

        if self._tray is not None:
            self._tray.setIcon(self._theme.make_tray_icon(unread, error=all_failed))
            self._tray.setToolTip(tray_tooltip(results))
            self._tray.setContextMenu(self._build_menu(for_tray=True))

    def _on_mark_read_requested(self, account_email: str, message_id: str) -> None:
        def _worker() -> None:
            try:
                updated = self.checker.mark_as_read(account_email, message_id)
                self._bridge.results_ready.emit(updated)
                self._bridge.status_message.emit("Marcada como lida")
            except Exception as e:
                log.warning("Failed to mark %s as read: %s", message_id, e)
                self._bridge.status_message.emit(f"Erro: {e}")

        threading.Thread(target=_worker, name="mark-read", daemon=True).start()

    def _on_message_selected(self, account_email: str, message) -> None:
        def _worker() -> None:
            try:
                body = self.checker.fetch_message_body(account_email, message.id)
                self._bridge.body_ready.emit(account_email, message.id, body, None)
            except Exception as e:
                log.warning("Failed to fetch body for %s: %s", message.id, e)
                self._bridge.body_ready.emit(account_email, message.id, None, str(e))

        threading.Thread(target=_worker, name="fetch-body", daemon=True).start()

    def _on_body_ready(self, account_email: str, message_id: str, body, error) -> None:
        if error:
            self._panel.show_message_error(account_email, message_id, str(error))
        elif body is not None:
            self._panel.show_message_body(account_email, message_id, body)

    def _on_code_copied(self, code: str) -> None:
        self._panel.set_status_feedback(f"Código {code} copiado!")

    def _check_now(self) -> None:
        self._wake.set()

    def _toggle_compact_dock(self) -> None:
        new_val = not self._bubble.compact_dock
        self._bubble.set_compact_dock(new_val)
        self.checker.state.set_ui("compact_dock", new_val, save=False)
        self.checker.state.set_ui("dock_edge", self._bubble.dock_edge, save=True)
        if self._tray is not None:
            self._tray.setContextMenu(self._build_menu(for_tray=True))

    def _toggle_bubble_visibility(self) -> None:
        if self._bubble.isVisible():
            self._panel.hide()
            self._bubble.hide()
        else:
            self._bubble.show()
            self._bubble.raise_()
        if self._tray is not None:
            self._tray.setContextMenu(self._build_menu(for_tray=True))

    def _open_config(self) -> None:
        open_path(self.config_path)

    def _open_settings(self) -> None:
        if self._settings_open:
            return
        from PySide6.QtWidgets import QDialog

        from ..notify import get_notifier
        from .settings_dialog import SettingsDialog

        self._settings_open = True
        if not self._pinned:
            self._panel.hide()
            self._bubble.set_panel_open(False)

        try:
            current_mode = self.checker.state.get_ui("view_mode", "unread")
            prev_scale = self._bubble.scale
            dlg = SettingsDialog(
                self.checker.config,
                self.config_path,
                compact_dock=self._bubble.compact_dock,
                view_mode=current_mode,
                bubble_scale=prev_scale,
                demo=self.demo,
            )
            dlg.reset_position_requested.connect(self._reset_position)
            dlg.bubble_scale_changed.connect(self._bubble.set_scale)
            dlg.account_reauthorized.connect(self.checker.invalidate_client)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_cfg = dlg.build_config()
                if not self.demo:
                    config.save(self.config_path, new_cfg)
                    dlg.apply_pending_deletions()
                self.checker.config = new_cfg
                if not self.demo:
                    self.checker.notifier = get_notifier(new_cfg.click_to_open)
                dlg.apply_autostart()

                scale = dlg.bubble_scale()
                self._bubble.set_scale(scale)
                self.checker.state.set_ui("bubble_scale", scale, save=False)

                compact = dlg.compact_dock_enabled()
                self._bubble.set_compact_dock(compact)
                self.checker.state.set_ui("compact_dock", compact, save=False)
                self.checker.state.set_ui("dock_edge", self._bubble.dock_edge, save=False)

                mode = dlg.default_view_mode()
                self._panel.set_view_mode(mode, emit=False)
                self.checker.state.set_ui("view_mode", mode, save=True)

                self._panel.set_status_feedback("Configurações salvas")
                self._wake.set()
            else:
                self._bubble.set_scale(prev_scale)
        finally:
            self._settings_open = False

    def _reload_config(self) -> None:
        if self.demo:
            self._panel.set_status_feedback("Modo demo ativo")
            return
        try:
            self.checker.config = config.load(self.config_path)
        except config.ConfigError as e:
            log.error("Reload failed: %s", e)
            self._panel.set_status_feedback(f"Erro na config: {e}")
            self.checker.notifier.send(Notification(f"{APP_NAME}: config error", str(e)))
            return
        self._wake.set()

    def _quit(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._tray is not None:
            self._tray.hide()
        self._panel.hide()
        self._bubble.hide()
        self._app.quit()

    # Context menus & tray click -----------------------------------------------

    def _on_tray_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if not self._bubble.isVisible():
                self._bubble.show()
            self._bubble.raise_()
            self._toggle_pin()

    def _show_context_menu(self, global_pos) -> None:
        menu = self._build_menu(for_tray=False)
        menu.exec(global_pos)

    def _build_menu(self, *, for_tray: bool):
        menu = self._qmenu_cls()
        menu.setStyleSheet(self._theme.PANEL_STYLESHEET)

        pin_act = self._qaction_cls("Desafixar painel" if self._pinned else "Fixar painel", menu)
        pin_act.triggered.connect(self._toggle_pin)
        menu.addAction(pin_act)

        check_act = self._qaction_cls("Verificar agora", menu)
        check_act.triggered.connect(self._check_now)
        menu.addAction(check_act)

        # Open Gmail (direct or per account)
        if len(self._results) == 1:
            email = self._results[0].account.email
            open_act = self._qaction_cls("Abrir Gmail", menu)
            open_act.triggered.connect(lambda _=False, e=email: open_url(inbox_url(e)))
            menu.addAction(open_act)
        elif len(self._results) > 1:
            sub = menu.addMenu("Abrir Gmail")
            for r in self._results:
                email = r.account.email
                act = self._qaction_cls(f"{r.account.name} ({r.count_label})", sub)
                act.triggered.connect(lambda _=False, e=email: open_url(inbox_url(e)))
                sub.addAction(act)

        menu.addSeparator()

        settings_act = self._qaction_cls("Configurações…", menu)
        settings_act.triggered.connect(self._open_settings)
        menu.addAction(settings_act)

        compact_act = self._qaction_cls("Modo compacto na borda", menu)
        compact_act.setCheckable(True)
        compact_act.setChecked(self._bubble.compact_dock)
        compact_act.triggered.connect(self._toggle_compact_dock)
        menu.addAction(compact_act)

        reset_act = self._qaction_cls("Resetar posição", menu)
        reset_act.triggered.connect(self._reset_position)
        menu.addAction(reset_act)

        if for_tray:
            vis_act = self._qaction_cls(
                "Ocultar pílula" if self._bubble.isVisible() else "Mostrar pílula", menu
            )
            vis_act.triggered.connect(self._toggle_bubble_visibility)
            menu.addAction(vis_act)

        if not self.demo:
            menu.addSeparator()
            cfg_act = self._qaction_cls("Abrir config.toml", menu)
            cfg_act.triggered.connect(self._open_config)
            menu.addAction(cfg_act)

            reload_act = self._qaction_cls("Recarregar configuração", menu)
            reload_act.triggered.connect(self._reload_config)
            menu.addAction(reload_act)

        menu.addSeparator()
        quit_act = self._qaction_cls("Sair", menu)
        quit_act.triggered.connect(self._quit)
        menu.addAction(quit_act)

        return menu
