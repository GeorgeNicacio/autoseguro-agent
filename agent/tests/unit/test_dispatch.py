"""Fila RQ: o webhook e o dashboard só enfileiram; o worker executa (REQ-90..92)."""

import fakeredis
from rq import Queue

from autoseguro_agent.dispatch import JOBS, RQDispatcher, RQTaskQueue


def queue() -> Queue:
    return Queue("agent", connection=fakeredis.FakeRedis())


async def test_message_is_enqueued_not_executed() -> None:
    q = queue()
    sub = await RQDispatcher(q).submit_message("c1", "oi", "text", "wamid.1")
    assert sub["status"] == "queued"
    job = q.fetch_job(sub["job_id"])
    assert job is not None
    assert job.func_name == f"{JOBS}.process_message_job"
    assert job.args == ("c1", "oi", "text", "wamid.1")


async def test_golden_is_a_job() -> None:
    q = queue()
    sub = await RQDispatcher(q).submit_golden("fake")
    assert q.fetch_job(sub["job_id"]).func_name == f"{JOBS}.run_golden_job"  # type: ignore[union-attr]


def test_quote_retry_is_scheduled_with_delay() -> None:
    q = queue()
    RQTaskQueue(q).schedule_quote_retry("c1", 2, 300)
    assert q.scheduled_job_registry.count == 1
    info = RQDispatcher(q).info()
    assert info["scheduled"] == 1
    assert info["mode"] == "queue"
