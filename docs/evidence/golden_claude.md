# Golden set com o Claude real

Mesmos 20 cenários do [golden set com FakeLLM](golden_report.md), agora com o Claude no
nó de extração (`--llm anthropic`, `effort: low`), contra o quote-service real sem falha
simulada. Medido em 2026-11-25.

| Rodada | Prompt | Resultado | O que falhou |
|---|---|---|---|
| 1 | `extract_v1` | 18 de 20 | G12, G16 |
| 2 | `extract_v2` (rascunho) | 17 de 20 | G03, G07 (variação), G17 |
| 3 | `extract_v2` | **20 de 20** | — ([relatório](golden_report_claude_run1.md)) |
| 4 | `extract_v2` | **20 de 20** | — ([relatório](golden_report_claude_run2.md)) |
| 5 | `extract_v2` | **20 de 20** | — ([relatório](golden_report_claude_run3.md)) |

Resultado final: **60 de 60** cenários em três rodadas seguidas com o prompt v2.

## O que cada falha ensinou

| Cenário | O que o Claude devolveu | Causa | Correção |
|---|---|---|---|
| G12 · CEP incompleto e depois "sei la" | CEP `1310-100` como texto (low), depois `other` | **Código:** CEP inválido contava como falha de formato, mas não como turno "empacado"; erro + sem resposta não chegava a 2 | Contador único de turnos sem o dado pendente, seja inválido ou ausente |
| G16 · "não sei, me indica" | só `plan_question` (diferença) | **Prompt + código:** não havia intenção de pedir recomendação; pergunta sobre planos bloqueava a recomendação | Intenção `wants_recommendation`; recomenda quando ela vier, mesmo junto de pergunta |
| G03 · "quero cotar meu Corolla 2003" | só o modelo, sem o ano, e `wants_to_buy` | **Prompt:** o modelo pareceu julgar o carro em vez de só extrair, e confundiu cotar com contratar | Regra "extraia mesmo se parecer fora da política"; `wants_to_buy` só para fechar cotação recebida; exemplo |
| G17 · "a franquia tá alta" | `complaint` + `plan_question` | **Prompt:** objeção de franquia lida como reclamação, que leva a handoff por conflito | `complaint` só para reclamação de atendimento/serviço; exemplo da franquia |
| G07 · foto e depois texto | passou na rodada seguinte sem mudança | variação do modelo | sem mudança; coberto pelas 3 rodadas verdes |

## Golden set ampliado (24 cenários) e prompt v3 (2026-11-26)

O teste manual no dashboard mostrou que o lead respondia "sim" à cotação e o agente
perguntava de novo. Entraram 4 cenários que vão até o fim do fluxo (G20 jornada completa,
G21 aceite curto "sim", G22 troca da data de início com pró-rata, G23 comparar com o
Premium e aceitar) e o G07b. O prompt `extract_v3` recebe a pergunta pendente do agente
(`<pergunta_pendente>`), e o cache de extração passou a incluir esse contexto na chave.

| Modelo | Prompt | Rodadas | Resultado |
|---|---|---|---|
| Opus 5.5 | `extract_v3` | 1 | **24 de 24** |
| Sonnet 5.5 | `extract_v3` | 2 | **24 de 24** nas duas |
| Haiku 5.5 | `extract_v3` | 1 | 22 de 24 (G01 só CEP, G23 nome do plano) |
| Haiku 5.5 | `extract_v3` + proteção determinística | 3 | **24 de 24** nas três |

A proteção determinística (`complete_unambiguous` em `graph/nodes.py`) preenche por código
o que não é ambíguo: um único token de CEP ou um único nome de plano na mensagem. Com ela,
o Haiku 5.5 virou o modelo padrão (ADR-017): ~33× mais barato que o Opus, mesma latência.
Custos e latências por modelo em [model_comparison.md](model_comparison.md).

As saídas reais do Claude nos casos G12 e G16 viraram testes de regressão com o FakeLLM
roteirizado (`tests/scenarios/test_flow.py`), que rodam offline em todo `make test`.
