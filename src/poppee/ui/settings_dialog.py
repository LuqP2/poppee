"""Modern dark PySide6 settings dialog eliminating the need for terminal commands."""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, auth, autostart, config
from ..config import Account, Config
from . import theme
from .query_builder import CATEGORIES, FilterSpec, build_query, parse_query

SETTINGS_QSS = f"""
QDialog {{
    background-color: #131720;
    color: #F1F5F9;
    font-family: {theme.FONT_FAMILY};
    font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    background-color: #161B26;
    padding: 8px;
}}
QTabBar::tab {{
    background: transparent;
    color: #94A3B8;
    padding: 7px 14px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: #161B26;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom: none;
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: #E2E8F0;
}}
QFrame#Card {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
}}
QLabel#SectionTitle {{
    font-size: 12px;
    font-weight: 600;
    color: #E2E8F0;
}}
QLabel#Muted {{
    font-size: 11px;
    color: #94A3B8;
}}
QLineEdit, QSpinBox, QComboBox {{
    background: #0F131B;
    color: #F1F5F9;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 7px;
    padding: 5px 8px;
    min-height: 20px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid rgba(96, 165, 250, 0.70);
}}
QComboBox QAbstractItemView {{
    background: #161B26;
    color: #F1F5F9;
    selection-background-color: rgba(96, 165, 250, 0.25);
    border: 1px solid rgba(255, 255, 255, 0.12);
}}
QListWidget {{
    background: #0F131B;
    color: #F1F5F9;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
    margin-bottom: 2px;
}}
QListWidget::item:selected {{
    background: rgba(96, 165, 250, 0.18);
    color: #F8FAFC;
}}
QListWidget::item:hover:!selected {{
    background: rgba(255, 255, 255, 0.05);
}}
QCheckBox {{
    color: #E2E8F0;
    spacing: 8px;
}}
QPushButton {{
    background: rgba(255, 255, 255, 0.07);
    color: #E2E8F0;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 7px;
    padding: 6px 12px;
    font-weight: 500;
}}
QPushButton:hover {{
    background: rgba(255, 255, 255, 0.12);
    color: #FFFFFF;
}}
QPushButton:disabled {{
    color: #64748B;
    background: rgba(255, 255, 255, 0.03);
}}
QPushButton#PrimaryBtn {{
    background: #2563EB;
    color: #FFFFFF;
    border: 1px solid #3B82F6;
    font-weight: 600;
}}
QPushButton#PrimaryBtn:hover {{
    background: #3B82F6;
}}
QPushButton#DangerBtn {{
    background: rgba(239, 68, 68, 0.14);
    color: #FCA5A5;
    border: 1px solid rgba(239, 68, 68, 0.30);
}}
QPushButton#DangerBtn:hover {{
    background: rgba(239, 68, 68, 0.25);
    color: #FEE2E2;
}}
"""


class AccountFilterDialog(QDialog):
    """Dialog to edit an account's display name, Gmail filters (sender/category/label) and flags."""

    def __init__(self, account: Account, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Filtros — {account.email}")
        self.setMinimumWidth(440)
        self.setStyleSheet(SETTINGS_QSS)
        self._account = account
        self._syncing = False

        spec = parse_query(account.query)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        self._name_edit = QLineEdit(account.name)
        self._name_edit.setPlaceholderText("Ex.: Trabalho, Pessoal")
        form.addRow("Nome de exibição:", self._name_edit)

        self._senders_edit = QLineEdit(", ".join(spec.senders))
        self._senders_edit.setPlaceholderText("Ex.: alerts@github.com, billing@stripe.com")
        self._senders_edit.textChanged.connect(self._rebuild_query)
        form.addRow("Remetentes:", self._senders_edit)

        self._category_combo = QComboBox()
        for key, label in CATEGORIES:
            self._category_combo.addItem(label, key)
        idx = self._category_combo.findData(spec.category)
        self._category_combo.setCurrentIndex(max(0, idx))
        self._category_combo.currentIndexChanged.connect(self._rebuild_query)
        form.addRow("Categoria:", self._category_combo)

        self._label_edit = QLineEdit(spec.label)
        self._label_edit.setPlaceholderText("Ex.: clientes, financeiro")
        self._label_edit.textChanged.connect(self._rebuild_query)
        form.addRow("Marcador (label):", self._label_edit)

        self._in_inbox_chk = QCheckBox("Restringir à Caixa de Entrada (in:inbox)")
        self._in_inbox_chk.setChecked(spec.in_inbox)
        self._in_inbox_chk.toggled.connect(self._rebuild_query)
        form.addRow("", self._in_inbox_chk)

        self._extra_edit = QLineEdit(spec.extra)
        self._extra_edit.setPlaceholderText("Ex.: has:attachment -subject:newsletter")
        self._extra_edit.textChanged.connect(self._rebuild_query)
        form.addRow("Termos extras:", self._extra_edit)

        self._query_edit = QLineEdit(account.query)
        self._query_edit.setPlaceholderText("is:unread in:inbox")
        form.addRow("Query do Gmail:", self._query_edit)

        self._enabled_chk = QCheckBox("Conta ativa (verificar periodicamente)")
        self._enabled_chk.setChecked(account.enabled)
        form.addRow("", self._enabled_chk)

        self._notify_chk = QCheckBox("Permitir notificações toast para esta conta")
        self._notify_chk.setChecked(account.notify)
        form.addRow("", self._notify_chk)

        layout.addLayout(form)

        hint = QLabel(
            "Dica: você pode combinar remetentes separados por vírgula ou editar a query."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Aplicar")
        save_btn.setObjectName("PrimaryBtn")
        save_btn.clicked.connect(self._on_accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    def _rebuild_query(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        senders = [s.strip() for s in self._senders_edit.text().split(",") if s.strip()]
        spec = FilterSpec(
            senders=senders,
            category=str(self._category_combo.currentData() or ""),
            label=self._label_edit.text().strip(),
            in_inbox=self._in_inbox_chk.isChecked(),
            unread_only=True,
            extra=self._extra_edit.text().strip(),
        )
        self._query_edit.setText(build_query(spec))
        self._syncing = False

    def _on_accept(self) -> None:
        if not self._query_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, "A query do Gmail não pode ficar vazia.")
            return
        self.accept()

    def updated_account(self) -> Account:
        return Account(
            email=self._account.email,
            name=self._name_edit.text().strip() or self._account.email,
            query=self._query_edit.text().strip() or config.DEFAULT_QUERY,
            notify=self._notify_chk.isChecked(),
            enabled=self._enabled_chk.isChecked(),
        )


class _OAuthSignals(QObject):
    finished = Signal(str, object)  # email, error_or_none


class SettingsDialog(QDialog):
    """Full settings dialog for accounts, OAuth, Gmail filters, widget behavior and autostart."""

    reset_position_requested = Signal()
    bubble_scale_changed = Signal(float)
    account_reauthorized = Signal(str)

    def __init__(
        self,
        cfg: Config,
        config_path: Path,
        *,
        compact_dock: bool,
        view_mode: str,
        bubble_scale: float = 1.0,
        demo: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Configurações")
        self.setMinimumSize(560, 470)
        self.setStyleSheet(SETTINGS_QSS)

        self._cfg = cfg
        self._config_path = config_path
        self._demo = demo
        self._accounts: list[Account] = list(cfg.accounts)
        self._pending_token_deletions: set[str] = set()
        self._client_secret_file: Path = cfg.client_secret_file
        self._oauth_busy = False
        self._oauth_signals = _OAuthSignals()
        self._oauth_signals.finished.connect(self._on_oauth_finished)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._build_accounts_tab(), "Contas e Filtros")
        tabs.addTab(
            self._build_general_tab(compact_dock, view_mode, bubble_scale), "Geral e Sistema"
        )
        root.addWidget(tabs, 1)

        footer = QHBoxLayout()
        self._footer_status = QLabel(
            "Modo demo: alterações não afetam sua conta real." if demo else ""
        )
        self._footer_status.setObjectName("Muted")
        footer.addWidget(self._footer_status, 1)

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Salvar")
        save_btn.setObjectName("PrimaryBtn")
        save_btn.clicked.connect(self.accept)
        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        self._refresh_secret_status()
        self._refresh_accounts_list()

    # Accounts & Filters tab ---------------------------------------------------

    def _build_accounts_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # OAuth client secret card
        oauth_card = QFrame()
        oauth_card.setObjectName("Card")
        ol = QHBoxLayout(oauth_card)
        ol.setContentsMargins(12, 10, 12, 10)
        ol.setSpacing(10)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        title = QLabel("Credencial OAuth2 do Google (client_secret.json)")
        title.setObjectName("SectionTitle")
        self._secret_status_lbl = QLabel()
        self._secret_status_lbl.setObjectName("Muted")
        self._secret_status_lbl.setWordWrap(True)
        info_col.addWidget(title)
        info_col.addWidget(self._secret_status_lbl)
        ol.addLayout(info_col, 1)

        self._pick_secret_btn = QPushButton("Selecionar JSON…")
        self._pick_secret_btn.clicked.connect(self._pick_client_secret)
        ol.addWidget(self._pick_secret_btn)
        lay.addWidget(oauth_card)

        # Accounts list header
        acc_hdr = QHBoxLayout()
        lbl = QLabel("Contas Gmail monitoradas")
        lbl.setObjectName("SectionTitle")
        acc_hdr.addWidget(lbl, 1)

        self._add_acc_btn = QPushButton("+ Adicionar conta")
        self._add_acc_btn.setObjectName("PrimaryBtn")
        self._add_acc_btn.clicked.connect(self._add_account)
        acc_hdr.addWidget(self._add_acc_btn)
        lay.addLayout(acc_hdr)

        self._acc_list = QListWidget()
        self._acc_list.itemDoubleClicked.connect(lambda _item: self._edit_selected_account())
        self._acc_list.currentRowChanged.connect(lambda _row: self._sync_account_buttons())
        lay.addWidget(self._acc_list, 1)

        # Account action bar
        act_row = QHBoxLayout()
        self._edit_acc_btn = QPushButton("Editar filtros…")
        self._edit_acc_btn.clicked.connect(self._edit_selected_account)
        self._reauth_btn = QPushButton("Reautorizar")
        self._reauth_btn.clicked.connect(self._reauth_selected_account)
        self._remove_acc_btn = QPushButton("Remover")
        self._remove_acc_btn.setObjectName("DangerBtn")
        self._remove_acc_btn.clicked.connect(self._remove_selected_account)

        act_row.addWidget(self._edit_acc_btn)
        act_row.addWidget(self._reauth_btn)
        act_row.addStretch(1)
        act_row.addWidget(self._remove_acc_btn)
        lay.addLayout(act_row)

        return tab

    # General & System tab -----------------------------------------------------

    def _build_general_tab(
        self, compact_dock: bool, view_mode: str, bubble_scale: float
    ) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(12)

        # Widget & Polling card
        w_card = QFrame()
        w_card.setObjectName("Card")
        wf = QFormLayout(w_card)
        wf.setContentsMargins(12, 10, 12, 10)
        wf.setSpacing(8)

        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(config.MIN_POLL_INTERVAL, 3600)
        self._poll_spin.setSingleStep(15)
        self._poll_spin.setSuffix(" s")
        self._poll_spin.setValue(max(config.MIN_POLL_INTERVAL, self._cfg.poll_interval))
        wf.addRow("Intervalo de verificação:", self._poll_spin)

        self._view_mode_combo = QComboBox()
        self._view_mode_combo.addItem("Mensagens não lidas", "unread")
        self._view_mode_combo.addItem("Mensagens recentes da inbox", "recent")
        idx = self._view_mode_combo.findData(view_mode)
        self._view_mode_combo.setCurrentIndex(max(0, idx))
        wf.addRow("Visualização padrão:", self._view_mode_combo)

        self._compact_chk = QCheckBox("Modo compacto na borda (recolher pílula parcialmente)")
        self._compact_chk.setChecked(compact_dock)
        wf.addRow("", self._compact_chk)

        scale_row = QHBoxLayout()
        scale_row.setSpacing(10)
        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(80, 180)
        self._scale_slider.setSingleStep(5)
        self._scale_slider.setPageStep(10)
        pct = max(80, min(180, round(bubble_scale * 100)))
        self._scale_slider.setValue(pct)
        self._scale_lbl = QLabel(f"{pct}%")
        self._scale_lbl.setFixedWidth(40)
        self._scale_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._scale_slider.valueChanged.connect(self._on_scale_slider_changed)
        scale_row.addWidget(self._scale_slider, 1)
        scale_row.addWidget(self._scale_lbl)
        wf.addRow("Tamanho do widget:", scale_row)

        reset_btn = QPushButton("Resetar posição e tamanho")
        reset_btn.clicked.connect(self.reset_position_requested.emit)
        wf.addRow("", reset_btn)
        lay.addWidget(w_card)

        # Notifications card
        n_card = QFrame()
        n_card.setObjectName("Card")
        nf = QFormLayout(n_card)
        nf.setContentsMargins(12, 10, 12, 10)
        nf.setSpacing(8)

        self._notif_chk = QCheckBox("Ativar notificações nativas do Windows")
        self._notif_chk.setChecked(self._cfg.notifications)
        nf.addRow("", self._notif_chk)

        self._max_notif_spin = QSpinBox()
        self._max_notif_spin.setRange(0, 20)
        self._max_notif_spin.setValue(self._cfg.max_notifications)
        nf.addRow("Máx. notificações individuais:", self._max_notif_spin)

        self._click_open_chk = QCheckBox("Abrir mensagem no Gmail ao clicar na notificação")
        self._click_open_chk.setChecked(self._cfg.click_to_open)
        nf.addRow("", self._click_open_chk)

        self._notify_existing_chk = QCheckBox("Notificar não lidas existentes ao iniciar")
        self._notify_existing_chk.setChecked(self._cfg.notify_existing_on_start)
        nf.addRow("", self._notify_existing_chk)
        lay.addWidget(n_card)

        # Windows Autostart card
        a_card = QFrame()
        a_card.setObjectName("Card")
        al = QHBoxLayout(a_card)
        al.setContentsMargins(12, 10, 12, 10)

        self._autostart_chk = QCheckBox("Iniciar automaticamente com o Windows")
        try:
            self._initial_autostart = autostart.get_autostart().is_enabled()
        except Exception:
            self._initial_autostart = False
        self._autostart_chk.setChecked(self._initial_autostart)
        if self._demo:
            self._autostart_chk.setToolTip("Desativado no modo demo para não alterar o Registro")
            self._autostart_chk.setEnabled(False)
        al.addWidget(self._autostart_chk, 1)
        lay.addWidget(a_card)

        lay.addStretch(1)
        return tab

    # Account & OAuth actions --------------------------------------------------

    def _refresh_secret_status(self) -> None:
        if self._demo:
            self._secret_status_lbl.setText("Modo demo — autenticação simulada.")
            self._pick_secret_btn.setEnabled(False)
            return
        if self._client_secret_file.exists():
            self._secret_status_lbl.setText(f"✓ Configurado em {self._client_secret_file}")
        else:
            self._secret_status_lbl.setText(
                "Não encontrado. Baixe o JSON OAuth 'Desktop app' no Google Cloud Console."
            )

    def _refresh_accounts_list(self) -> None:
        current = self._acc_list.currentRow()
        self._acc_list.clear()
        for acc in self._accounts:
            flags: list[str] = []
            if not acc.enabled:
                flags.append("desativada")
            if not self._demo and not auth.has_token(acc.email):
                flags.append("sem login")
            status = f"  [{', '.join(flags)}]" if flags else ""
            text = f"{acc.name}  <{acc.email}>{status}\nFiltro: {acc.query}"
            self._acc_list.addItem(QListWidgetItem(text))
        if self._accounts:
            self._acc_list.setCurrentRow(min(max(0, current), len(self._accounts) - 1))
        self._sync_account_buttons()

    def _sync_account_buttons(self) -> None:
        has_sel = 0 <= self._acc_list.currentRow() < len(self._accounts)
        self._edit_acc_btn.setEnabled(has_sel and not self._oauth_busy)
        self._reauth_btn.setEnabled(has_sel and not self._oauth_busy and not self._demo)
        self._remove_acc_btn.setEnabled(has_sel and not self._oauth_busy)
        self._add_acc_btn.setEnabled(not self._oauth_busy)

    def _pick_client_secret(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar client_secret.json",
            str(Path.home() / "Downloads"),
            "Arquivos JSON (*.json)",
        )
        if not file_path:
            return
        src = Path(file_path)
        dest = self._client_secret_file
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            os.chmod(dest, 0o600)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Erro ao copiar arquivo OAuth: {e}")
            return
        self._refresh_secret_status()
        self._footer_status.setText("Arquivo client_secret.json instalado com sucesso.")

    def _add_account(self) -> None:
        if self._demo:
            QMessageBox.information(
                self,
                APP_NAME,
                "No modo demo as contas são fictícias. Você já pode testar 'Editar filtros…'!",
            )
            return
        if not self._client_secret_file.exists():
            QMessageBox.warning(
                self,
                APP_NAME,
                "Selecione primeiro o arquivo client_secret.json antes de adicionar uma conta.",
            )
            return
        self._start_oauth(login_hint=None)

    def _reauth_selected_account(self) -> None:
        row = self._acc_list.currentRow()
        if row < 0 or row >= len(self._accounts):
            return
        self._start_oauth(login_hint=self._accounts[row].email)

    def _start_oauth(self, *, login_hint: str | None) -> None:
        self._oauth_busy = True
        self._sync_account_buttons()
        self._footer_status.setText("Abrindo navegador para login Google…")

        def _worker() -> None:
            try:
                from google.auth.transport.requests import AuthorizedSession

                from ..gmail import GmailClient

                creds = auth.authorize(self._client_secret_file, login_hint=login_hint)
                email = GmailClient(AuthorizedSession(creds)).email_address()
                auth.save_credentials(email, creds)
                self._oauth_signals.finished.emit(email, None)
            except Exception as e:
                self._oauth_signals.finished.emit("", e)

        threading.Thread(target=_worker, name="oauth-signin", daemon=True).start()

    def _on_oauth_finished(self, email: str, error: object) -> None:
        self._oauth_busy = False
        if error is not None:
            self._footer_status.setText("Falha na autenticação.")
            QMessageBox.warning(self, APP_NAME, f"Não foi possível conectar a conta:\n{error}")
            self._sync_account_buttons()
            return

        self._pending_token_deletions.discard(email.lower())
        self.account_reauthorized.emit(email)
        if not any(a.key == email.lower() for a in self._accounts):
            self._accounts.append(Account(email=email, name=email.split("@")[0]))
            self._footer_status.setText(f"Conta {email} conectada!")
        else:
            self._footer_status.setText(f"Conta {email} reautorizada!")
        self._refresh_accounts_list()

    def _edit_selected_account(self) -> None:
        row = self._acc_list.currentRow()
        if row < 0 or row >= len(self._accounts):
            return
        dlg = AccountFilterDialog(self._accounts[row], parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._accounts[row] = dlg.updated_account()
            self._refresh_accounts_list()

    def _remove_selected_account(self) -> None:
        row = self._acc_list.currentRow()
        if row < 0 or row >= len(self._accounts):
            return
        acc = self._accounts[row]
        ans = QMessageBox.question(
            self,
            "Remover conta",
            f"Remover {acc.name} <{acc.email}> e apagar o token salvo?",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._accounts.pop(row)
        if not self._demo:
            self._pending_token_deletions.add(acc.email.lower())
        self._refresh_accounts_list()

    def apply_pending_deletions(self) -> None:
        """Delete OAuth tokens for removed accounts only after settings are saved."""
        if self._demo:
            return
        for email in self._pending_token_deletions:
            auth.delete_credentials(email)
        self._pending_token_deletions.clear()

    # Result accessors ---------------------------------------------------------

    def build_config(self) -> Config:
        return Config(
            client_secret_file=self._client_secret_file,
            accounts=list(self._accounts),
            poll_interval=self._poll_spin.value(),
            notifications=self._notif_chk.isChecked(),
            max_notifications=self._max_notif_spin.value(),
            notify_existing_on_start=self._notify_existing_chk.isChecked(),
            click_to_open=self._click_open_chk.isChecked(),
            path=self._config_path,
        )

    def _on_scale_slider_changed(self, value: int) -> None:
        self._scale_lbl.setText(f"{value}%")
        self.bubble_scale_changed.emit(value / 100.0)

    def bubble_scale(self) -> float:
        return self._scale_slider.value() / 100.0

    def compact_dock_enabled(self) -> bool:
        return self._compact_chk.isChecked()

    def default_view_mode(self) -> str:
        return str(self._view_mode_combo.currentData() or "unread")

    def apply_autostart(self) -> None:
        if self._demo:
            return
        desired = self._autostart_chk.isChecked()
        if desired == self._initial_autostart:
            return
        target = autostart.get_autostart()
        if desired:
            target.enable(autostart.launch_command())
        else:
            target.disable()
