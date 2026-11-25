"""Nós do grafo. Um nó de LLM (`extract`); o resto é código determinístico.

Fluxo de um turno:

    ingest -> extract -> apply -> route ─┬─> handoff ──────────────┐
                                         ├─> quote -> route_quote ─┼─> present ─┐
                                         │                         └─> handoff  ├─> deliver
                                         └─> respond ──────────────────────────┘

Toda mensagem passa por `deliver`, que roda o validador de saída antes de enviar.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from autoseguro_agent import templates
from autoseguro_agent.domain.eligibility import (
    PolicyRefusal,
    default_start_date,
    policy_refusal,
    validate_data_inicio,
    validate_idade,
    validate_plano,
    validate_veiculo_ano,
)
from autoseguro_agent.domain.events import Event, EventType
from autoseguro_agent.domain.extraction import ExtractionRequest, ExtractionResult, Intent
from autoseguro_agent.domain.handoff import HandoffContext, HandoffDecision, decide_handoff
from autoseguro_agent.domain.models import LeadProfile, QuoteRequest, QuoteResult
from autoseguro_agent.domain.output_validator import validate_output
from autoseguro_agent.domain.quote import QuoteOutcome, TraceContext
from autoseguro_agent.domain.recommendation import recommend_plan
from autoseguro_agent.graph.state import ConversationState
from autoseguro_agent.pii import cep_log_prefix
from autoseguro_agent.ports import (
    Clock,
    EventStore,
    LLMClient,
    LLMUnavailableError,
    OutboundChannel,
    QuoteGateway,
    Vault,
)

PII_TO_NOTICE = {"CPF", "EMAIL", "TEL", "PLACA"}
Update = dict[str, Any]


@dataclass
class Deps:
    llm: LLMClient
    gateway: QuoteGateway
    events: EventStore
    outbound: OutboundChannel
    clock: Clock
    vault: Vault
    wait_message_after_s: float = 4.0
    tasks: Any = None  # TaskQueue (fila): agenda retry da cotação após handoff de infra
    # LLMs disponíveis por nome ("fake", "anthropic"); a conversa escolhe qual usar.
    # Vazio: sempre `llm`.
    llms: dict[str, Any] = field(default_factory=dict)
    quote_retry_delays_s: tuple[int, ...] = (60, 300, 900)


class Nodes:
    def __init__(self, deps: Deps) -> None:
        self.d = deps

    # ------------------------------------------------------------------ trace
    def traced(self, name: str, fn: Any) -> Any:
        """Envolve um nó: cada execução vira um span `trace.span` com a duração (REQ-81)."""
        if asyncio.iscoroutinefunction(fn):

            async def run_async(s: ConversationState) -> Update:
                t0 = self.d.clock.monotonic()
                out: Update = await fn(s)
                self._span(s, name, t0)
                return out

            return run_async

        def run(s: ConversationState) -> Update:
            t0 = self.d.clock.monotonic()
            out: Update = fn(s)
            self._span(s, name, t0)
            return out

        return run

    def _span(self, s: ConversationState, name: str, t0: float) -> None:
        ms = int((self.d.clock.monotonic() - t0) * 1000)
        self.emit(s, "trace.span", "ok", latency_ms=ms, payload={"node": name})

    # ------------------------------------------------------------------ util
    def emit(self, s: ConversationState, event_type: EventType, status: str, **kw: Any) -> None:
        payload = kw.pop("payload", {})
        self.d.events.append(
            Event(
                ts=self.d.clock.now(),
                event_type=event_type,
                conversation_id=s["conversation_id"],
                message_id=s["turn"]["message_id"] if "turn" in s else None,
                status=status,
                payload=payload,
                **kw,
            )
        )

    def llm_for(self, s: ConversationState) -> LLMClient:
        """LLM escolhido para a conversa (dashboard); senão, o padrão do ambiente."""
        choice = s.get("llm_provider")
        return self.d.llms.get(choice, self.d.llm) if choice else self.d.llm

    @staticmethod
    def profile(s: ConversationState) -> LeadProfile:
        return LeadProfile.model_validate(s.get("profile") or {})

    @staticmethod
    def last_success(s: ConversationState) -> QuoteResult | None:
        data = s.get("last_success")
        return QuoteResult.model_validate(data) if data else None

    @staticmethod
    def intents(s: ConversationState) -> frozenset[Intent]:
        ex = s.get("extraction")
        return frozenset(ex.get("intents", [])) if ex else frozenset()

    def today(self) -> date:
        return self.d.clock.today()

    # --------------------------------------------------------------- ingest
    def ingest(self, s: ConversationState) -> Update:
        """Zera o que é do turno e conta mídia (o agente não lê mídia)."""
        update: Update = {
            "extraction": None,
            "turn_errors": [],
            "turn_policy": None,
            "turn_quote": None,
            "turn_handoff": None,
            "turn_recommended": None,
            "early_sent": [],
            "turn_llm_failed": False,
            "outbox": [],
        }
        if not s.get("status"):
            update |= {
                "status": "active",
                "profile": {},
                "slot_failures": {},
                "low_confidence_streak": 0,
                "media_strikes": 0,
                "quotes": [],
                "pending_slot": None,
            }
        if s["turn"]["message_type"] != "text":
            update["media_strikes"] = s.get("media_strikes", 0) + 1
        return update

    # -------------------------------------------------------------- extract
    def extract(self, s: ConversationState) -> Update:
        """O único nó com LLM. Recebe texto mascarado; devolve só dados e intenções."""
        if s["turn"]["message_type"] != "text" or s.get("status") == "handed_off":
            return {}
        p = self.profile(s)
        known = {k: str(v) for k, v in p.model_dump(exclude_none=True).items()}
        req = ExtractionRequest(
            masked_text=s["turn"]["text"],
            pending_slot=s.get("pending_slot"),
            known_slots=known,
            today_iso=self.today().isoformat(),
        )
        try:
            llm = self.llm_for(s)
            result = llm.extract(req)
        except LLMUnavailableError as exc:
            self.emit(s, "llm.error", "failed", payload={"error": type(exc).__name__})
            # 2 falhas seguidas do LLM viram handoff `stuck` (mesma regra de "empacou").
            return {
                "turn_llm_failed": True,
                "low_confidence_streak": s.get("low_confidence_streak", 0) + 1,
            }
        stats = getattr(llm, "last_stats", None)
        if stats is not None:  # REQ-80: tokens, custo, latência e cache de cada chamada
            self.emit(
                s, "llm.call", stats.cache, latency_ms=stats.latency_ms, payload=stats.as_payload()
            )
        return {"extraction": result.model_dump(mode="json")}

    # ---------------------------------------------------------------- apply
    def apply(self, s: ConversationState) -> Update:
        """Aplica os slots extraídos com validação local e checa a política."""
        ex_data = s.get("extraction")
        profile = self.profile(s)
        failures = dict(s.get("slot_failures", {}))
        streak = s.get("low_confidence_streak", 0)
        errors: list[str] = []
        changes: dict[str, Any] = {}
        update: Update = {}
        pending = s.get("pending_slot")
        today = self.today()

        if ex_data:
            ex = ExtractionResult.model_validate(ex_data)
            filled_high = False

            def take(slot: str, value: Any, error: Any) -> None:
                nonlocal filled_high
                if error is not None:
                    errors.append(slot)
                    failures[slot] = failures.get(slot, 0) + 1
                    self.emit(s, "slot.invalid", error.code, payload={"slot": slot})
                else:
                    changes[slot] = value
                    filled_high = True

            if ex.veiculo_ano:
                if ex.veiculo_ano.confidence == "high":
                    v = ex.veiculo_ano.value
                    take("veiculo_ano", v, validate_veiculo_ano(v, today))
                elif pending == "veiculo_ano":
                    streak += 1
            if ex.veiculo_modelo and ex.veiculo_modelo.confidence == "high":
                changes["veiculo_modelo"] = ex.veiculo_modelo.value
            if ex.idade:
                if ex.idade.confidence == "high":
                    take("idade", ex.idade.value, validate_idade(ex.idade.value))
                elif pending == "idade":
                    streak += 1
            if ex.cep_token:
                token = ex.cep_token.value
                resolved = self.d.vault.resolve(s["conversation_id"], token)
                if resolved is None:  # o lead digitou algo que não é CEP completo
                    errors.append("cep")
                    failures["cep"] = failures.get("cep", 0) + 1
                    self.emit(s, "slot.invalid", "cep_invalido", payload={"slot": "cep"})
                else:
                    changes["cep_token"] = token
                    filled_high = True
            if ex.plano_id:
                take("plano_id", ex.plano_id, validate_plano(ex.plano_id, self.d.gateway.rules()))
            if ex.data_inicio and ex.data_inicio.confidence == "high":
                try:
                    inicio = date.fromisoformat(ex.data_inicio.value)
                    take("data_inicio", inicio, validate_data_inicio(inicio, today))
                except ValueError:
                    errors.append("data_inicio")
                    failures["data_inicio"] = failures.get("data_inicio", 0) + 1

            # REQ-06: perguntado o plano, o lead pede indicação ou não escolhe nenhum ->
            # recomendação por regra. Pergunta sobre os planos sem pedir indicação é
            # respondida e o plano segue pendente.
            wants_rec = "wants_recommendation" in ex.intents
            no_plan_answer = (
                pending == "plano_id"
                and "plano_id" not in changes
                and "plano_id" not in errors
                and (wants_rec or "plan_question" not in ex.intents)
            )
            if no_plan_answer:
                rec = recommend_plan(changes.get("veiculo_ano", profile.veiculo_ano), today)
                changes["plano_id"] = rec
                update["turn_recommended"] = rec
                filled_high = True

            # "Empacou" = turnos seguidos sem conseguir o dado pedido, seja porque veio
            # inválido, seja porque não veio. 2 seguidos -> handoff `stuck`. Achado no
            # golden set com o Claude real: CEP inválido + "sei la" não contava como 2.
            pending_key = "cep_token" if pending == "cep" else pending
            got_pending = pending_key is not None and pending_key in changes
            only_noise = set(ex.intents) <= {"other", "greeting"}
            if pending and not got_pending and (pending in errors or only_noise):
                streak += 1
            elif filled_high:
                streak = 0
            if filled_high:
                update["media_strikes"] = 0  # mídia conta "2× no mesmo dado pendente"

        if "data_inicio" in changes:
            update["start_date_default"] = False
        new_profile = profile.model_copy(update=changes)
        for slot, value in changes.items():
            shown = (
                cep_log_prefix(self.d.vault.resolve(s["conversation_id"], value) or "")
                if (slot == "cep_token")
                else value
            )
            self.emit(s, "slot.updated", "ok", payload={"slot": slot, "value": str(shown)})

        refusal = policy_refusal(new_profile, self.d.gateway.rules(), today)
        if refusal:
            self.emit(s, "policy.refused", refusal.code, payload={"motivo": refusal.motivo})

        missing = new_profile.missing_slots()
        update |= {
            "profile": new_profile.model_dump(mode="json"),
            "slot_failures": failures,
            "low_confidence_streak": streak,
            "turn_errors": errors,
            "turn_policy": {"code": refusal.code, "motivo": refusal.motivo} if refusal else None,
            "pending_slot": errors[0] if errors else (missing[0] if missing else None),
        }
        return update

    # ---------------------------------------------------------------- route
    def handoff_context(self, s: ConversationState) -> HandoffContext:
        q = s.get("turn_quote") or {}
        pol = s.get("turn_policy")
        failures = s.get("slot_failures", {})
        media = s.get("media_strikes", 0) if s["turn"]["message_type"] != "text" else 0
        return HandoffContext(
            intents=self.intents(s),
            quote_status=q.get("status"),
            failure_reason=q.get("failure_reason"),
            invalid_reason=q.get("invalid_reason"),
            api_refusal_motivo=q.get("refusal_motivo"),
            policy_refusal=PolicyRefusal(pol["code"], pol["motivo"]) if pol else None,
            max_slot_failures=max(failures.values(), default=0),
            low_confidence_streak=s.get("low_confidence_streak", 0),
            media_strikes=media,
            quoted=s.get("status") == "quoted",
        )

    def _decision(self, s: ConversationState) -> dict[str, str] | None:
        d: HandoffDecision | None = decide_handoff(self.handoff_context(s))
        return {"rule_id": d.rule_id, "priority": d.priority, "motivo": d.motivo} if d else None

    def route(self, s: ConversationState) -> Update:
        if s.get("status") == "handed_off":
            return {}
        return {"turn_handoff": self._decision(s)}

    def next_after_route(self, s: ConversationState) -> str:
        if s.get("status") == "handed_off":
            return "respond"
        if s.get("turn_handoff"):
            return "handoff"
        if self._needs_quote(s):
            return "quote"
        return "respond"

    def _quote_key(self, p: LeadProfile) -> str:
        return f"{p.plano_id}|{p.data_inicio or 'default'}"

    def _needs_quote(self, s: ConversationState) -> bool:
        if s["turn"]["message_type"] != "text" or s.get("turn_errors"):
            return False
        p = self.profile(s)
        if p.missing_slots():
            return False
        return s.get("quoted_key") != self._quote_key(p)

    # ---------------------------------------------------------------- quote
    def quote_request_for(self, s: ConversationState) -> tuple[QuoteRequest, bool]:
        """Monta o pedido a partir do perfil; o CEP real sai do cofre só aqui."""
        p = self.profile(s)
        assert p.cep_token
        assert p.plano_id
        assert p.idade is not None
        assert p.veiculo_ano is not None
        cep = self.d.vault.resolve(s["conversation_id"], p.cep_token)
        inicio = p.data_inicio or default_start_date(self.today())
        req = QuoteRequest(
            plano_id=p.plano_id,
            idade=p.idade,
            veiculo_ano=p.veiculo_ano,
            cep=cep or "",
            data_inicio=inicio,
        )
        return req, p.data_inicio is None

    def record_quote(
        self,
        s: ConversationState,
        req: QuoteRequest,
        outcome: QuoteOutcome,
        total_ms: int,
        **extra: Any,
    ) -> dict[str, Any]:
        """Eventos do pedido e de cada tentativa; devolve o resumo guardado no estado."""
        payload = {
            "plano_id": req.plano_id,
            "data_inicio": req.data_inicio.isoformat() if req.data_inicio else None,
            **extra,
        }
        self.emit(
            s,
            "quote_request.started",
            "pending",
            quote_request_id=outcome.quote_request_id,
            payload=payload,
        )
        for a in outcome.attempts:
            self.emit(
                s,
                "quote_attempt",
                a.status,
                quote_request_id=outcome.quote_request_id,
                quote_attempt_id=a.quote_attempt_id,
                latency_ms=a.latency_ms,
                payload={"attempt": a.attempt, "http_status": a.http_status},
            )
        self.emit(
            s,
            "quote_request.finished",
            outcome.status,
            quote_request_id=outcome.quote_request_id,
            latency_ms=total_ms,
            payload={
                "attempts": len(outcome.attempts),
                "premio_mensal": str(outcome.result.premio_mensal) if outcome.result else None,
                "failure_reason": outcome.failure_reason,
                "invalid_reason": outcome.invalid_reason,
                "cache": outcome.cache,
                "saved_ms": outcome.saved_ms,
                **extra,
            },
        )
        return {
            "quote_request_id": outcome.quote_request_id,
            "status": outcome.status,
            "plano_id": req.plano_id,
            "cache": outcome.cache,
            "attempts": [a.model_dump(mode="json") for a in outcome.attempts],
        }

    async def quote(self, s: ConversationState) -> Update:
        p = self.profile(s)
        req, default_date = self.quote_request_for(s)
        ctx = TraceContext(conversation_id=s["conversation_id"], message_id=s["turn"]["message_id"])
        t0 = self.d.clock.monotonic()
        outcome, early = await self._quote_with_wait_message(s, req, ctx)
        total_ms = int((self.d.clock.monotonic() - t0) * 1000)  # inclui backoff entre tentativas
        summary = self.record_quote(s, req, outcome, total_ms)
        update: Update = {
            "early_sent": early,
            "turn_quote": outcome.model_dump(mode="json", exclude={"result"}),
            "quotes": [*s.get("quotes", []), summary],
        }
        if outcome.status == "success" and outcome.result is not None:
            update |= {
                "last_success": outcome.result.model_dump(mode="json"),
                "quoted_key": self._quote_key(p),
                "status": "quoted",
                "start_date_default": default_date,
            }
            self.emit(s, "conversation.status", "quoted")
        return update

    async def _quote_with_wait_message(
        self, s: ConversationState, req: QuoteRequest, ctx: TraceContext
    ) -> tuple[QuoteOutcome, list[str]]:
        """REQ-23: no WhatsApp silêncio parece abandono. Passou do limite, avisa e segue."""
        task = asyncio.create_task(self.d.gateway.quote(req, ctx))
        done, _ = await asyncio.wait({task}, timeout=self.d.wait_message_after_s)
        early: list[str] = []
        if not done:
            # 1º turno: a saudação sai antes da espera (achado no teste em Docker).
            texts = [] if s.get("greeted") else [templates.greeting()]
            texts.append(templates.waiting())
            for text in texts:
                self.d.outbound.send(s["conversation_id"], text)
                kind = "waiting" if text == templates.waiting() else "greeting"
                self.emit(
                    s,
                    "message.sent",
                    "sent",
                    payload={"chars": len(text), "text": text, "kind": kind},
                )
                early.append(text)
        return await task, early

    def route_quote(self, s: ConversationState) -> Update:
        q = s.get("turn_quote") or {}
        if q.get("status") == "success":
            return {"turn_handoff": None}
        return {"turn_handoff": self._decision(s)}

    def next_after_quote(self, s: ConversationState) -> str:
        return "handoff" if s.get("turn_handoff") else "present"

    # -------------------------------------------------------------- present
    def present(self, s: ConversationState) -> Update:
        result = self.last_success(s)
        assert result is not None
        out = list(s.get("outbox", []))
        out += self._prefix_messages(s)
        if s.get("turn_recommended"):
            out.append(templates.recommended_plan(result.plano_nome))
        announce_date = (
            s.get("start_date_default")
            and len([q for q in s.get("quotes", []) if q["status"] == "success"]) == 1
        )
        if announce_date:  # avisa a data padrão só na 1ª cotação
            out.append(templates.confirm_start_date(default_start_date(self.today())))
        out.append(
            templates.quote_message(
                result, self.d.gateway.rules(), offer_others=bool(s.get("turn_recommended"))
            )
        )
        return {"outbox": out}

    # -------------------------------------------------------------- respond
    @staticmethod
    def _greeted(s: ConversationState) -> bool:
        return bool(s.get("greeted")) or templates.greeting() in s.get("early_sent", [])

    def _prefix_messages(self, s: ConversationState) -> list[str]:
        out: list[str] = []
        if not self._greeted(s):
            out.append(templates.greeting())
        kinds = set(s["turn"]["pii_kinds"]) & PII_TO_NOTICE
        if kinds and not s.get("pii_notice_sent"):
            out.append(templates.unsolicited_pii_notice())
        return out

    def respond(self, s: ConversationState) -> Update:
        out = list(s.get("outbox", []))
        if s.get("status") == "handed_off":
            return {"outbox": [templates.already_handed_off()]}
        out += self._prefix_messages(s)
        if s.get("turn_llm_failed"):
            return {"outbox": [*out, templates.llm_unavailable()]}
        intents = self.intents(s)
        ex = s.get("extraction") or {}
        rules = self.d.gateway.rules()
        quoted = s.get("status") == "quoted"
        pending = s.get("pending_slot")

        if s["turn"]["message_type"] != "text":
            out.append(templates.media_ack())
        if "plan_question" in intents or ("compare_plans" in intents and not quoted):
            out.append(templates.plan_info(rules, ex.get("plan_question_topic")))

        if s.get("turn_errors"):
            slot = s["turn_errors"][0]
            if slot == "data_inicio":
                out.append(templates.ask_data_inicio_retry())
            else:
                out.append(templates.ask_slot(slot, retry=True))  # type: ignore[arg-type]
        elif pending:
            low = s.get("low_confidence_streak", 0) > 0
            out.append(templates.ask_slot(pending, retry=low))  # type: ignore[arg-type]
        elif quoted:
            if "will_think" in intents:
                out.append(templates.will_think())
            elif "compare_plans" in intents:
                out.append(templates.ask_which_plan_to_compare())
            elif not out:
                out.append(templates.after_quote_prompt())
        return {"outbox": out}

    # -------------------------------------------------------------- handoff
    def handoff(self, s: ConversationState) -> Update:
        decision = s.get("turn_handoff")
        assert decision is not None
        handoff_id = f"ho_{s['turn']['message_id']}"
        summary = {
            "handoff_id": handoff_id,
            "rule_id": decision["rule_id"],
            "priority": decision["priority"],
            "motivo": decision["motivo"],
            "profile": s.get("profile", {}),  # mascarado: CEP como token
            "quotes": s.get("quotes", []),
            "last_message": s["turn"]["text"],  # mascarado
        }
        self.emit(s, "handoff.opened", "opened", handoff_id=handoff_id, payload=summary)
        self.emit(s, "conversation.status", "handed_off")
        retry_scheduled = False
        if decision["rule_id"] == "infra_unavailable" and self.d.tasks is not None:
            # REQ-91: o legado pode voltar logo; a fila tenta de novo em segundo plano.
            delay = self.d.quote_retry_delays_s[0] if self.d.quote_retry_delays_s else 60
            self.d.tasks.schedule_quote_retry(s["conversation_id"], 1, delay)
            self.emit(
                s,
                "quote_retry.scheduled",
                "scheduled",
                handoff_id=handoff_id,
                payload={"attempt": 1, "delay_s": delay},
            )
            retry_scheduled = True

        rule = decision["rule_id"]
        out = list(s.get("outbox", []))
        if not self._greeted(s):
            out.append(templates.greeting())
        message = {
            "infra_unavailable": templates.quote_unavailable,
            "ready_to_close": templates.ready_to_close,
            "out_of_scope": templates.out_of_scope,
        }.get(rule)
        if rule == "infra_unavailable" and retry_scheduled:
            out.append(templates.quote_unavailable() + " " + templates.retry_promise())
        elif rule == "out_of_policy":
            out.append(templates.policy_refused(decision["motivo"]))
        elif message is not None:
            out.append(message())
        else:
            out.append(templates.handoff_notice())
        return {"outbox": out, "status": "handed_off", "handoff": summary}

    # -------------------------------------------------------------- deliver
    def deliver(self, s: ConversationState) -> Update:
        """Validador de saída em toda mensagem, inclusive aviso de handoff (REQ-13)."""
        last = self.last_success(s)
        rules = self.d.gateway.rules()
        sent: list[str] = []
        for text in s.get("outbox", []):
            check = validate_output(text, last, rules)
            if not check.ok:
                self.emit(s, "output.blocked", "blocked", payload={"offending": check.offending})
                text = templates.safe_fallback()
            self.d.outbound.send(s["conversation_id"], text)
            # Texto do agente vai no evento (templates não ecoam dado pessoal do lead).
            self.emit(s, "message.sent", "sent", payload={"chars": len(text), "text": text})
            sent.append(text)
        kinds = set(s["turn"]["pii_kinds"]) & PII_TO_NOTICE
        return {
            "outbox": sent,
            "greeted": True,
            "pii_notice_sent": bool(s.get("pii_notice_sent") or kinds),
        }
