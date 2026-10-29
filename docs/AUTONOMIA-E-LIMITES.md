# Rodadas de trabalho e recuperação

Os limites preservam checkpoints e não ampliam a pasta ou as ferramentas autorizadas.

| Configuração | Antes | Padrão atual | Variável opcional |
| --- | --- | --- | --- |
| Ciclos de implementação por rodada | 12 | 48 | `CENTRAL_WORKER_MAX_ROUNDS` |
| Ações por rodada | 18 | 42 | `CENTRAL_WORKER_MAX_ACTIONS` |
| Ciclos de planejamento | 6 | 12 | `CENTRAL_WORKER_PLANNING_ROUNDS` |
| Retomadas por trabalhador | 8 | 24 | `CENTRAL_WORKER_MAX_RESUMES` |

Valores são limitados internamente para manter as execuções finitas. As mudanças
de ambiente entram em vigor ao reiniciar API e worker com a mesma configuração.
Rodadas maiores permitem mais chamadas e podem consumir mais tokens.

## Recuperação de falhas

- Seis ciclos sem nova ação bem-sucedida provocam failover do provedor. Repetir
  a mesma leitura sem alteração de conteúdo não conta como novo progresso.
- Pasta vazia pode ser inicializada com `mkdir`/`write`; não exige ler um arquivo
  inexistente. Arquivos existentes continuam protegidos por SHA.
- O pedido completo é recuperado ao retomar checkpoints antigos. O limite antigo
  de 16 mil caracteres cortava a parte final de briefs maiores.
- Saídas de leitura não são mais cortadas em 11 mil caracteres, preservando o fim
  dos arquivos e seus hashes para correções seguras.
- Respostas de implementação permitem até 8.192 tokens (antes 3.000), com
  orientação de dividir arquivos grandes em componentes menores. Isso evita
  perder um arquivo inteiro por JSON cortado no limite de saída.
- Builds e testes npm existentes são executados na validação final. Validar só o
  build não substitui os testes quando ambos existem.
- Alterar um arquivo invalida as observações de navegador do trabalhador, exigindo
  nova inspeção quando a tarefa pede validação visual.

## Caso de reprodução

Na tarefa `8f99ff10-c581-4b8c-bdfe-8191f8128813`, o Frontend tinha 113 ciclos,
oito retomadas e nenhum arquivo alterado. O brief tinha 17.394 caracteres e o
checkpoint antigo preservava até 16.000 por mensagem. A pasta autorizada era
`GPT 222`; respostas de pasta vazia eram interpretadas como falta de permissão.

Após as correções, o fluxo passou a criar os arquivos reais do projeto AURA.
O código do site continua sendo produzido pelos trabalhadores da Central.
O cumprimento visual completo do brief depende de build, testes e inspeção da
página final; a existência dos arquivos não é aprovação da entrega.
