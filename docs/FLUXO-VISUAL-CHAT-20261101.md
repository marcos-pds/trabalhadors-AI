# Fluxo visual dentro do chat

A apresentação de `central_ia_showcase.tsx`, fornecida pelo usuário, foi adaptada para a atividade real da Central: etapa atual, trabalhadores, mensagem registrada e três registros recentes em um terminal compacto.

O cartão usa a consulta de atividade existente. Identidades, modelos e dependências vêm das etapas; mensagens vêm do histórico persistido. Sem uma mensagem entre agentes, a interface identifica explicitamente a próxima etapa dependente, sem inventar diálogo. Conclusão da execução não significa entrega verificada: esse selo exige a confirmação do backend.

Pausa, falha e indisponibilidade de atualização interrompem as animações. A apresentação respeita movimento reduzido e telas pequenas. A lista detalhada de etapas fica recolhida, mas abre quando existe aprovação pendente. O acesso à execução e à prévia permanece disponível.

O endpoint continua exigindo propriedade da execução. Os novos metadados não incluem credenciais nem conteúdo de arquivos. Nenhuma chamada adicional a modelos foi introduzida.

Validação: 76 testes de frontend e 10 testes direcionados de backend passaram. A aceitação Electron utiliza dados controlados, explicitamente marcados como fixture, para verificar mensagens, logs, layout móvel e pausa. Esses testes comprovam a apresentação; não representam execução autônoma de um projeto por modelos.
