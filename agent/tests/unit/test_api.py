"""Webhook no formato WhatsApp, deduplicação e linha do tempo (REQ-42, 43, 60)."""

import json
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


# --- fase 4: dashboard, chat, golden e métricas -----------------------------------


def test_dashboard_page(client: TestClient) -> None:
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_manual_chat_then_metrics_and_trace(client: TestClient) -> None:
    first = client.post("/api/chat", json={"text": "Oi, tenho um Onix 2022"}).json()
    conv = first["conversation_id"]
    assert first["status"] == "finished"
    assert any("idade" in m.lower() for m in first["messages"])
    client.post(
        "/api/chat", json={"conversation_id": conv, "text": "35 anos, cep 01310-100, completo"}
    )
    job = client.get(f"/api/jobs/{first['job_id']}").json()
    assert job["status"] == "finished"

    m = client.get("/api/metrics").json()
    assert m["conversations"]["total"] == 1
    assert m["quote"]["requests"] == {"success": 1}
    assert m["llm"]["calls"] == 2
    assert m["config"]["queue"] == "inline"

    convs = client.get("/api/conversations").json()
    assert convs[0]["status"] == "quoted"
    detail = client.get(f"/api/conversations/{conv}").json()
    assert len(detail["turns"]) == 2
    assert detail["turns"][1]["spans"]
    assert "01310-100" not in json.dumps(detail)


def test_media_from_dashboard(client: TestClient) -> None:
    first = client.post("/api/chat", json={"text": "Oi, tenho um Onix 2022"}).json()
    r = client.post(
        "/api/chat", json={"conversation_id": first["conversation_id"], "message_type": "audio"}
    ).json()
    assert "Não preciso desse arquivo" in r["messages"][0]


def test_chat_rejects_unavailable_llm(client: TestClient) -> None:
    r = client.post("/api/chat", json={"text": "oi", "llm": "anthropic"})
    assert r.status_code == 400
    assert client.get("/api/metrics").json()["config"]["llm_options"] == ["fake"]


def test_chat_with_explicit_fake_llm(client: TestClient) -> None:
    r = client.post("/api/chat", json={"text": "Oi, tenho um Onix 2022", "llm": "fake"})
    assert r.status_code == 200
    assert any("idade" in m.lower() for m in r.json()["messages"])


def test_chat_rejects_unknown_model(client: TestClient) -> None:
    assert (
        client.post("/api/chat", json={"text": "oi", "llm": "claude-haiku-5-5"}).status_code == 400
    )
    assert client.get("/api/golden/history").json() == []
