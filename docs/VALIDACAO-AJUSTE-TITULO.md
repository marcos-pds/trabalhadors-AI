# Validação de alteração curta de texto

Pedido reproduzido:

> Transformamos ideias em experiências extraordinárias.
>
> altere esse titulo para, essa pagina foi feita por mim app central

## Causa observada

A execução `e788c51d-ad54-472f-89c3-ea185356cd17` classificou o pedido como
`conversation`, com `autonomous=0`, e marcou conclusão sem ferramentas locais.
O classificador não incluía os verbos “altere”, “mude” e “troque”.

## Correção

- Classificação de verbos de alteração e elementos de interface como edição real.
- Pedidos sem autonomia agora recebem o bloqueio explícito já existente na API;
  não são enviados ao Coordenador como conversa concluída.
- Ajustes literais curtos seguem diretamente para implementação e revisão.
- O pedido atual tem prioridade sobre textos antigos recuperados da memória.
- O trabalhador e a verificação final conferem o texto nos arquivos salvos.
  Para títulos estáticos, verificam o conteúdo de `h1`/`title`, não comentários.
- Build permanece obrigatório; uma troca literal não exige auditoria Lighthouse
  completa, salvo pedido explícito de navegador.

## Reprodução real após a correção

Execução `4e4a5808-5bca-41e0-8359-214605cf465a`, na mesma conversa e pasta
autorizada, criada pelo serviço normal de execução da Central com o pedido acima.

- Frontend IA leu e alterou `src/App.tsx` por `replace` com SHA.
- O `h1` passou a conter exatamente `essa pagina foi feita por mim app central`.
- Revisor IA leu o arquivo alterado e confirmou a troca.
- `npm_build` aprovado após a alteração, incluindo a revisão.
- Estado final: `completed`, sem erro.

Regressão: 486 testes aprovados, 26 ignorados. Inclui pedido exato, sinônimos,
pedidos de explicação sem autorização de edição, roteamento de duas etapas e
rejeição de conclusão quando o trabalhador altera um arquivo sem relação com o título.
