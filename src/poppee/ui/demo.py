"""Demo mode with realistic mock accounts and messages for fast visual iteration."""

from __future__ import annotations

import tempfile
import time
from dataclasses import replace
from pathlib import Path

from ..checker import Checker
from ..config import Account, Config
from ..gmail import GmailError, Message
from ..state import State


class _SilentNotifier:
    name = "demo-silent"

    def send(self, _notification) -> bool:
        return True


class DemoGmailClient:
    """In-memory GmailClient replacement supporting unread, inbox_recent, and mark_as_read."""

    def __init__(self, messages: list[Message]):
        self._messages = list(messages)

    def unread_ids(self, query: str, limit: int = 100) -> tuple[list[str], bool]:
        if "is:unread" in query.lower():
            ids = [m.id for m in self._messages if m.unread][:limit]
        else:
            ids = [m.id for m in self._messages][:limit]
        return ids, False

    def message(self, msg_id: str) -> Message:
        for m in self._messages:
            if m.id == msg_id:
                return m
        raise GmailError(f"Demo message not found: {msg_id}")

    def mark_as_read(self, msg_id: str) -> None:
        self._messages = [replace(m, unread=False) if m.id == msg_id else m for m in self._messages]


def build_demo_checker() -> tuple[Checker, Path]:
    """Create an isolated Checker populated with realistic sample emails."""
    now = time.time()
    personal = Account(email="ana.costa@gmail.com", name="Pessoal")
    work = Account(email="ana@studio.dev", name="Trabalho")

    personal_msgs = [
        Message(
            id="demo-p1",
            thread_id="tp1",
            sender="GitHub",
            sender_email="notifications@github.com",
            subject="[xpoppee] PR #12: Widget flutuante em PySide6 aprovado",
            snippet="Ótimo trabalho no modo compacto com encaixe na borda. Merge liberado!",
            timestamp=now - 120,
            unread=True,
        ),
        Message(
            id="demo-p2",
            thread_id="tp2",
            sender="Nubank",
            sender_email="todomundo@nubank.com.br",
            subject="Sua fatura de novembro fechou",
            snippet="Confira o resumo da sua fatura com vencimento em 28/11.",
            timestamp=now - 1400,
            unread=True,
        ),
        Message(
            id="demo-p3",
            thread_id="tp3",
            sender="Spotify",
            sender_email="no-reply@spotify.com",
            subject="Novidades da semana na sua Radar de Novidades",
            snippet="Separamos lançamentos recentes dos artistas que você mais ouve.",
            timestamp=now - 7200,
            unread=False,
        ),
        Message(
            id="demo-p4",
            thread_id="tp4",
            sender="Amazon Brasil",
            sender_email="shipment@amazon.com.br",
            subject="Seu pedido foi entregue",
            snippet="O pacote foi entregue no endereço cadastrado hoje às 11:20.",
            timestamp=now - 26000,
            unread=False,
        ),
    ]

    work_msgs = [
        Message(
            id="demo-w1",
            thread_id="tw1",
            sender="Marina Oliveira",
            sender_email="marina@studio.dev",
            subject="Alinhamento de design — protótipo desktop v2",
            snippet=(
                "Subi os ajustes de contraste e opacidade no Figma. "
                "Pode dar uma olhada antes das 17h?"
            ),
            timestamp=now - 420,
            unread=True,
        ),
        Message(
            id="demo-w2",
            thread_id="tw2",
            sender="Linear",
            sender_email="notifications@linear.app",
            subject="DES-148 atribuída a você: Animação de hover",
            snippet="Prioridade alta · Ciclo 14 · Comentário adicionado por Rafael.",
            timestamp=now - 4800,
            unread=False,
        ),
        Message(
            id="demo-w3",
            thread_id="tw3",
            sender="Google Calendar",
            sender_email="calendar-notification@google.com",
            subject="Convite: Review semanal de produto @ Sex 10:00",
            snippet="Você aceitou este convite. Link do Meet incluso na descrição.",
            timestamp=now - 90000,
            unread=False,
        ),
    ]

    clients = {
        personal.email: DemoGmailClient(personal_msgs),
        work.email: DemoGmailClient(work_msgs),
    }

    tmp_dir = Path(tempfile.mkdtemp(prefix="poppee-demo-"))
    cfg_path = tmp_dir / "config.toml"
    cfg = Config(
        client_secret_file=tmp_dir / "client_secret.json",
        accounts=[personal, work],
        poll_interval=300,
        notifications=False,
        path=cfg_path,
    )
    state = State(tmp_dir / "state.json")
    checker = Checker(
        cfg,
        state,
        _SilentNotifier(),
        client_factory=lambda a: clients[a.email],
    )
    return checker, cfg_path
