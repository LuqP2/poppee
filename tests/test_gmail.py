import base64

import pytest
import requests
from google.auth.exceptions import RefreshError

from poppee.gmail import API_ROOT, AuthError, GmailClient, GmailError, Message, inbox_url


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.text = str(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, routes=None, exc=None):
        self.routes = routes or {}
        self.exc = exc
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self.exc:
            raise self.exc
        return self.routes[url]

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        if self.exc:
            raise self.exc
        return self.routes[url]


def test_unread_ids():
    session = FakeSession(
        {
            API_ROOT + "/messages": FakeResponse(
                200, {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "x"}
            )
        }
    )
    ids, more = GmailClient(session).unread_ids("is:unread", limit=2)
    assert ids == ["a", "b"] and more
    assert session.calls[0][1] == {"q": "is:unread", "maxResults": 2}


def test_unread_ids_empty_mailbox():
    session = FakeSession({API_ROOT + "/messages": FakeResponse(200, {"resultSizeEstimate": 0})})
    assert GmailClient(session).unread_ids("is:unread") == ([], False)


def test_message_parsing():
    payload = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "Tom &amp; Jerry&#39;s reply",
        "internalDate": "1700000000000",
        "payload": {
            "headers": [
                {"name": "From", "value": '"Game Forum" <noreply@forum.example>'},
                {"name": "Subject", "value": "New reply"},
            ]
        },
    }
    session = FakeSession({API_ROOT + "/messages/m1": FakeResponse(200, payload)})
    m = GmailClient(session).message("m1")
    assert m == Message(
        "m1",
        "t1",
        "Game Forum",
        "noreply@forum.example",
        "New reply",
        "Tom & Jerry's reply",
        1_700_000_000.0,
    )
    assert (
        m.url("me+x@gmail.com")
        == "https://mail.google.com/mail/?authuser=me%2Bx%40gmail.com#all/t1"
    )
    assert Message.from_dict(m.to_dict()) == m


def test_message_without_headers():
    session = FakeSession({API_ROOT + "/messages/m1": FakeResponse(200, {"id": "m1"})})
    m = GmailClient(session).message("m1")
    assert m.subject == "(no subject)" and m.sender == "(unknown sender)" and m.thread_id == "m1"


def test_http_errors():
    err = {"error": {"message": "Invalid Credentials"}}
    with pytest.raises(AuthError, match="Invalid Credentials"):
        GmailClient(FakeSession({API_ROOT + "/profile": FakeResponse(401, err)})).email_address()
    with pytest.raises(GmailError, match="HTTP 429"):
        GmailClient(FakeSession({API_ROOT + "/profile": FakeResponse(429, err)})).email_address()


def test_refresh_and_network_errors():
    with pytest.raises(AuthError, match="add-account"):
        GmailClient(FakeSession(exc=RefreshError("invalid_grant"))).email_address()
    with pytest.raises(GmailError, match="network"):
        GmailClient(FakeSession(exc=requests.ConnectionError("down"))).email_address()


def test_inbox_url():
    assert inbox_url("a@gmail.com") == "https://mail.google.com/mail/?authuser=a%40gmail.com#inbox"


def test_message_read_label_and_mark_as_read():
    payload = {"id": "m2", "labelIds": ["INBOX"]}
    session = FakeSession(
        {
            API_ROOT + "/messages/m2": FakeResponse(200, payload),
            API_ROOT + "/messages/m2/modify": FakeResponse(
                200, {"id": "m2", "labelIds": ["INBOX"]}
            ),
        }
    )
    client = GmailClient(session)
    assert client.message("m2").unread is False
    client.mark_as_read("m2")
    assert session.calls[-1] == (API_ROOT + "/messages/m2/modify", {"removeLabelIds": ["UNREAD"]})

    forbidden = FakeSession(
        {
            API_ROOT + "/messages/m2/modify": FakeResponse(
                403, {"error": {"message": "Insufficient Permission"}}
            )
        }
    )
    with pytest.raises(AuthError, match="gmail.modify"):
        GmailClient(forbidden).mark_as_read("m2")


def test_message_body_decodes_multipart_mime():
    plain_b64 = base64.urlsafe_b64encode("Olá, código 482910".encode()).decode()
    html_b64 = base64.urlsafe_b64encode(b"<p>Ola <b>482910</b></p>").decode()
    payload = {
        "id": "m3",
        "payload": {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": plain_b64}},
                {"mimeType": "text/html", "body": {"data": html_b64}},
            ],
        },
    }
    session = FakeSession({API_ROOT + "/messages/m3": FakeResponse(200, payload)})
    body = GmailClient(session).message_body("m3")
    assert body.id == "m3"
    assert "482910" in body.text
    assert "<b>482910</b>" in body.html
