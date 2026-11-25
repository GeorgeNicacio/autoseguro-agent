"""Todas as mensagens que o lead recebe com números, ou em situação de falha.

Regra de ouro: o LLM nunca escreve valores. Valores entram aqui só a partir de
`QuoteResult` (resposta 200 do /quote) ou de `PlanRules` (GET /planos), e toda
mensagem ainda passa pelo `validate_output` antes de sair.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from autoseguro_agent.domain.extraction import PlanTopic
from autoseguro_agent.domain.models import QuoteResult, SlotName
from autoseguro_agent.domain.rules import PlanRules

COVERAGE_NAMES = {
    "colisao": "colisão",
    "roubo": "roubo",
    "furto": "furto",
    "terceiros": "danos a terceiros",
    "vidros": "vidros",
    "carro_reserva": "carro reserva",
    "assistencia_24h": "assistência 24h",
}

_ASK = {
    "veiculo_ano": "Pra começar, qual é o modelo e o ano do seu carro?",
    "idade": "Qual é a sua idade?",
    "cep": "Qual é o CEP de onde o carro fica à noite?",
    "plano_id": (
        "Temos três planos: Essencial, Completo e Premium. "
        "Já tem um em mente ou quer que eu recomende?"
    ),
}
_ASK_RETRY = {
    "veiculo_ano": "Não consegui entender o ano do carro. Pode me dizer só o ano, tipo 2019?",
    "idade": "Não consegui entender a idade. Pode me dizer só o número, tipo 35?",
    "cep": "Esse CEP não parece completo. Pode mandar os 8 números, com ou sem hífen?",
    "plano_id": "Qual desses você prefere: Essencial, Completo ou Premium?",
}


def format_brl(value: Decimal) -> str:
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer, cents = f"{q:.2f}".split(".")
    groups = f"{int(integer):,}".replace(",", ".")
    return f"R$ {groups},{cents}"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " e " + items[-1]


def _coverages(codes: tuple[str, ...]) -> str:
    return _join([COVERAGE_NAMES.get(c, c) for c in codes])


def ask_slot(slot: SlotName, *, retry: bool = False) -> str:
    return (_ASK_RETRY if retry else _ASK)[slot]


def confirm_start_date(inicio: date) -> str:
    return (
        f"Vou considerar o início da vigência em {inicio:%d/%m/%Y}. "
        "Se preferir outra data, é só me dizer."
    )


def quote_message(result: QuoteResult, rules: PlanRules, *, offer_others: bool = False) -> str:
    lines = [
        f"Prontinho! Cotação do plano {result.plano_nome}:",
        f"• Mensalidade: {format_brl(result.premio_mensal)}",
        f"• Franquia: {format_brl(result.franquia)}",
        f"• Coberturas: {_coverages(result.coberturas)}",
    ]
    if result.carencia.coberturas:
        lines.append(
            f"• Carência de {result.carencia.dias} dias para "
            f"{_coverages(result.carencia.coberturas)}, a partir do início da vigência"
        )
    pr = result.primeiro_pagamento_pro_rata
    if pr is not None:
        lines.append(
            f"• Primeiro pagamento proporcional: {format_brl(pr.valor_primeiro_pagamento)} "
            f"({pr.dias_cobrados} dias); depois, mensalidade cheia"
        )
    if offer_others:
        others = [f"o {p.nome}" for p in rules.plans if p.id != result.plano_id]
        lines.append(f"Se quiser, também cotamos {_join(others)}.")
    lines.append("Quer seguir com esse plano?")
    return "\n".join(lines)


def plan_info(rules: PlanRules, topic: PlanTopic | None) -> str:
    """Dúvida sobre planos respondida só com GET /planos, sem preço."""
    if topic == "franquia":
        parts = [f"{p.nome}: {format_brl(Decimal(p.franquia))}" for p in rules.plans]
        return "Franquia por plano: " + "; ".join(parts) + "."
    if topic == "carencia":
        return (
            f"Roubo e furto têm carência de {rules.carencia_dias} dias a partir do início "
            "da vigência. As outras coberturas valem desde o início."
        )
    parts = [f"{p.nome}: {_coverages(p.coberturas)}" for p in rules.plans]
    return "Coberturas por plano — " + "; ".join(parts) + "."


def waiting() -> str:
    return "Estou calculando sua cotação, só um instante."


def quote_unavailable() -> str:
    return (
        "O sistema de cotação está instável agora e não quero te passar um valor errado. "
        "Já encaminhei seus dados para um consultor, que vai te enviar a cotação por aqui."
    )


def retry_promise() -> str:
    return "Se o sistema voltar antes, eu mesmo te mando a cotação aqui."


def quote_recovered() -> str:
    return "Boa notícia: o sistema de cotação voltou e já consegui o seu valor."


def policy_refused(motivo: str) -> str:
    return (
        f"Infelizmente não consigo cotar automaticamente: {motivo} "
        "Vou te passar para um consultor, que pode avaliar o seu caso."
    )


def greeting() -> str:
    return (
        "Olá! Sou o assistente virtual da AutoSeguro e vou te ajudar a cotar o seguro do seu carro."
    )


def ask_data_inicio_retry() -> str:
    return (
        "A data de início precisa ser hoje ou depois. Qual data você prefere? "
        "Se não tiver preferência, uso o dia 1º do próximo mês."
    )


def recommended_plan(plan_name: str) -> str:
    return f"Pelo seu perfil, recomendo começar pelo plano {plan_name}. Vou cotar pra você."


def after_quote_prompt() -> str:
    return "Quer seguir com esse plano, cotar outro plano ou mudar a data de início?"


def ask_which_plan_to_compare() -> str:
    return "Quer que eu cote qual deles: Essencial, Completo ou Premium?"


def out_of_scope() -> str:
    return (
        "Esse assunto é tratado pelos nossos consultores. "
        "Já te encaminhei e alguém continua com você por aqui."
    )


def already_handed_off() -> str:
    return "Um consultor já está com o seu atendimento e te responde por aqui em instantes."


def handoff_notice() -> str:
    return "Vou te passar para um consultor, que continua o atendimento por aqui."


def ready_to_close() -> str:
    return (
        "Ótimo! Para contratar, um consultor vai seguir com você por aqui para "
        "os documentos e o pagamento."
    )


def media_ack() -> str:
    return "Obrigado! Não preciso desse arquivo agora. Pode me responder por texto?"


def unsolicited_pii_notice() -> str:
    return (
        "Obrigado! Para a cotação não preciso de CPF, e-mail, telefone ou placa — "
        "pode ficar tranquilo."
    )


def will_think() -> str:
    return "Sem problema! Fico à disposição. É só me chamar aqui quando quiser continuar."


def llm_unavailable() -> str:
    return "Tive um probleminha aqui. Pode repetir a sua última mensagem?"


def safe_fallback() -> str:
    """Usado quando o validador bloqueia uma mensagem: nunca sai valor não verificado."""
    return "Deixa eu confirmar essa informação com um consultor antes de te responder."
