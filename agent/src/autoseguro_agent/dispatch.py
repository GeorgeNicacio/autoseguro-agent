"""Despachante: manda trabalho para a fila (RQ) ou executa na hora (sem Redis).

Por que fila (REQ-90..92):
- o WhatsApp reenvia a mensagem se o webhook não responde rápido; enfileirar e
  responder 200 na hora desacopla a resposta HTTP do tempo do LLM e do /quote;
- um worker processa em ordem, sem dois escritores no checkpoint;
- tarefas atrasadas (retry da cotação em 1/5/15 min) e longas (golden set) saem do
  caminho da requisição.

Por que RQ e não Celery/SQS/Kafka: neste teste o Redis já existe para o cache, e RQ
é uma fila mínima em cima dele. Em produção a recomendação está no README.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol

from rq import Queue
from rq.job import Job

from autoseguro_agent.agent import Agent, MessageType

QUEUE_NAME = "agent"
JOBS = "autoseguro_agent.jobs"


class Dispatcher(Protocol):
    mode: str

    async def submit_message(
        self,
        conversation_id: str,
        text: str,
        message_type: MessageType,
        wa_message_id: str | None = None,
        llm: str | None = None,
    ) -> dict[str, Any]: ...

    async def submit_golden(self, llm: str) -> dict[str, Any]: ...
    def job(self, job_id: str) -> dict[str, Any]: ...
    def info(self) -> dict[str, Any]: ...


class RQTaskQueue:
    """Porta TaskQueue sobre RQ: agenda o retry da cotação (precisa do --with-scheduler)."""

    def __init__(self, queue: Queue) -> None:
        self._q = queue

    def schedule_quote_retry(self, conversation_id: str, attempt: int, delay_s: int) -> None:
        self._q.enqueue_in(
            timedelta(seconds=delay_s),
            f"{JOBS}.retry_quote_job",
            conversation_id,
            attempt,
            job_timeout=120,
        )


class RQDispatcher:
    mode = "queue"

    def __init__(self, queue: Queue) -> None:
        self._q = queue

    async def submit_message(
        self,
        conversation_id: str,
        text: str,
        message_type: MessageType,
        wa_message_id: str | None = None,
        llm: str | None = None,
    ) -> dict[str, Any]:
        job = self._q.enqueue(
            f"{JOBS}.process_message_job",
            conversation_id,
            text,
            message_type,
            wa_message_id,
            llm,
            job_timeout=120,
            result_ttl=3600,
        )
        return {"job_id": job.id, "status": "queued", "messages": []}

    async def submit_golden(self, llm: str) -> dict[str, Any]:
        job = self._q.enqueue(f"{JOBS}.run_golden_job", llm, job_timeout=1800, result_ttl=86_400)
        return {"job_id": job.id, "status": "queued"}

    def job(self, job_id: str) -> dict[str, Any]:
        job = Job.fetch(job_id, connection=self._q.connection)
        status = job.get_status()
        return {
            "job_id": job_id,
            "status": str(getattr(status, "value", status)),
            "result": job.return_value(),
            "error": (job.exc_info or "")[-500:] or None,
        }

    def info(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "queued": self._q.count,
            "scheduled": self._q.scheduled_job_registry.count,
            "started": self._q.started_job_registry.count,
            "failed": self._q.failed_job_registry.count,
            "finished": self._q.finished_job_registry.count,
        }


class InlineDispatcher:
    """Sem Redis (testes, CLI): executa na hora e guarda o resultado em memória."""

    mode = "inline"

    def __init__(self, agent: Agent, golden_runner: Any = None) -> None:
        self._agent = agent
        self._golden = golden_runner
        self._jobs: dict[str, dict[str, Any]] = {}

    async def submit_message(
        self,
        conversation_id: str,
        text: str,
        message_type: MessageType,
        wa_message_id: str | None = None,
        llm: str | None = None,
    ) -> dict[str, Any]:
        messages = await self._agent.handle(
            conversation_id,
            text,
            message_type=message_type,
            wa_message_id=wa_message_id,
            llm=llm,
        )
        job_id = f"inline_{len(self._jobs) + 1}"
        result = {"conversation_id": conversation_id, "messages": messages}
        self._jobs[job_id] = {"job_id": job_id, "status": "finished", "result": result}
        return {"job_id": job_id, "status": "finished", "messages": messages}

    async def submit_golden(self, llm: str) -> dict[str, Any]:
        job_id = f"inline_{len(self._jobs) + 1}"
        result = await self._golden(llm) if self._golden else {"error": "golden indisponível"}
        self._jobs[job_id] = {"job_id": job_id, "status": "finished", "result": result}
        return {"job_id": job_id, "status": "finished"}

    def job(self, job_id: str) -> dict[str, Any]:
        return self._jobs.get(job_id, {"job_id": job_id, "status": "unknown", "result": None})

    def info(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "queued": 0,
            "scheduled": 0,
            "started": 0,
            "failed": 0,
            "finished": len(self._jobs),
        }
