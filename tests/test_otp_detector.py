"""Unit tests for verification / OTP / 2FA code extraction (PT-BR & EN)."""

import pytest

from poppee.ui.otp_detector import extract_verification_code, strip_html


@pytest.mark.parametrize(
    "subject, body, expected",
    [
        ("Seu código de verificação é 482910", "", "482910"),
        ("[GitHub] Código de verificação: 482 910", "", "482910"),
        ("Use 739-204 as your login code", "", "739204"),
        ("Google verification", "Use G-839201 to verify your account.", "G-839201"),
        ("Facebook security", "FB-91827 is your confirmation code", "FB-91827"),
        (
            "Confirmação de acesso",
            "Seu código de confirmação:\n\n847291\n\nExpira em 5 min.",
            "847291",
        ),
        (
            "One-time passcode",
            "<p>Your <b>passcode</b> is:</p><div style='font-size:24px'>904128</div>",
            "904128",
        ),
        ("Código de segurança", "Código: A7K9P2 — válido por 10 minutos", "A7K9P2"),
        ("2FA authentication", "Enter 12345678 to complete sign-in.", "12345678"),
        ("Verify your email", "Your verification PIN is 4912.", "4912"),
    ],
)
def test_extracts_real_verification_codes(subject, body, expected):
    assert extract_verification_code(subject, body) == expected


@pytest.mark.parametrize(
    "subject, body",
    [
        ("Sua fatura de novembro fechou", "Valor total: R$ 1540,00 com vencimento em 28/11/2026."),
        ("Pedido #482910 aprovado", "Seu pedido #482910 foi enviado hoje às 14:30."),
        ("Newsletter 2026", "Confira as novidades de 2026 em https://example.com/post/847291"),
        ("Promoção imperdível", "Economize $2500 hoje — 50% OFF em toda a loja!"),
        ("Reunião semanal", "Vamos nos falar amanhã sobre o roadmap do Q4."),
    ],
)
def test_rejects_false_positives(subject, body):
    assert extract_verification_code(subject, body) is None


def test_strip_html_removes_styles_and_scripts():
    raw = (
        "<html><style>.x { color: #123456; }</style>"
        "<script>var a=999999;</script><p>Código: <b>654321</b></p></html>"
    )
    assert "123456" not in strip_html(raw)
    assert "999999" not in strip_html(raw)
    assert extract_verification_code("", raw) == "654321"
