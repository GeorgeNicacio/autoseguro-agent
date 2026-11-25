"""Webhook no formato WhatsApp, deduplicação e linha do tempo (REQ-42, 43, 60)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from autoseguro_agent.api import conversation_id_for, create_api
from tests.fakes import make_agent

PHONE = "5511987654321"


def wa(text: str | None, msg_id: str, mtype: str = "text") -> dict[str, Any]:
    message: dict[str, Any] = {
        "from": PHONE,
        "id": msg_id,
        "timestamp": "1764072000",
        "type": mtype,
    }
    if text is not None:
        message["text"] = {"body": text}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {"id": "1", "changes": [{"field": "messages", "value": {"messages": [message]}}]}
        ],
    }


@pytest.fixture
def client() -> TestClient:
    agent, _, _, events = make_agent()
    return TestClient(create_api(agent, events))


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_text_message_gets_replies(client: TestClient) -> None:
    body = client.post("/webhook/whatsapp", json=wa("Oi, tenho um Onix 2022", "wamid.1")).json()
    result = body["results"][0]
    assert result["conversation_id"] == conversation_id_for(PHONE)
    assert PHONE not in result["conversation_id"]
    assert any("idade" in m.lower() for m in result["messages"])


def test_redelivery_is_deduplicated(client: TestClient) -> None:
    first = client.post("/webhook/whatsapp", json=wa("Oi", "wamid.2")).json()["results"][0]
    again = client.post("/webhook/whatsapp", json=wa("Oi", "wamid.2")).json()["results"][0]
    assert first["messages"]
    assert again["messages"] == []
    assert again["duplicate"] is True


def test_media_message(client: TestClient) -> None:
    client.post("/webhook/whatsapp", json=wa("Oi, tenho um Onix 2022", "wamid.3"))
    r = client.post("/webhook/whatsapp", json=wa(None, "wamid.4", mtype="audio")).json()
    assert "Não preciso desse arquivo" in r["results"][0]["messages"][0]


def test_timeline_endpoint(client: TestClient) -> None:
    client.post(
        "/webhook/whatsapp", json=wa("35 anos, Onix 2022, cep 01310-100, completo", "wamid.5")
    )
    conv = conversation_id_for(PHONE)
    data = client.get(f"/conversations/{conv}").json()
    assert data["status"] == "quoted"
    types = [e["event_type"] for e in data["events"]]
    assert "quote_attempt" in types
    assert data["quotes"][0]["status"] == "success"
    assert "01310-100" not in str(data)  # CEP real não sai na linha do tempo


def test_unknown_conversation_is_404(client: TestClient) -> None:
    assert client.get("/conversations/nao-existe").status_code == 404
