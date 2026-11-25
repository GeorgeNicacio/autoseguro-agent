# Notas para o ai-logs/README.md (preencher durante o desafio)

Momentos em que a IA errou ou o plano foi corrigido, e como foi pego.

1. **Plano em PDF × código do quote-service (Dia 0).** O plano dizia que dado mal formatado gera 400; lendo o código, plano inexistente gera 422 `cotacao_recusada` e o exemplo do README usa uma data já no passado. Registrado em `docs/sdd/01-requirements.md` §5.
2. **"Temperatura 0" (Dia 0).** O plano pedia temperatura 0 na extração; a API atual do Claude rejeita `temperature` (400). Trocado por saída estruturada + `effort: low` + validação em código.
3. **Regex de uso comercial (Dia 1, T1.3).** A primeira versão da análise contou 448 conversas com "uso comercial"; o padrão incluía `99` (de "99 Pop") e casava com dígitos de telefone e CPF. Conferido contra o gerador do dataset (que não tem esse caso) → corrigido com limites de palavra → 0.
4. **Mídia como gatilho de handoff (Dia 1, T1.3).** O design inicial passava para humano já na 1ª mídia; o dataset mostrou mídia em 56,8% das conversas → regra mudada para 2 mídias no mesmo dado pendente.
5. **Circuit breaker por tentativa (Dia 2, T2.6).** A primeira versão contava cada tentativa falha. O teste de caos passou nos três critérios, mas o sucesso foi 10%: o breaker abria com a API só instável e mandava 84% dos leads para humano. Mudado para contar pedidos que falharam depois dos retries → 52% de sucesso sob caos, 97% na configuração padrão. Os dois relatórios estão em `docs/evidence/`.
6. **Timeout do httpx não basta (Dia 2, T2.2).** O teste com resposta lenta simulada mostrou que o timeout do httpx vale por operação de rede; foi adicionado `asyncio.timeout` em volta da tentativa inteira.
