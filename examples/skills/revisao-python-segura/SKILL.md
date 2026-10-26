---
name: revisao-python-segura
description: Checklist de revisão manual de código Python com foco em segurança e clareza
version: 1.0.0
---

# Revisão segura de código Python

Revise somente o código que o usuário fornecer ou associar explicitamente a esta tarefa dentro do workspace autorizado.

## Verificações

1. Procure erros de lógica, casos de borda e validação insuficiente de entradas.
2. Confira tratamento de erros, recursos que precisam ser fechados e mensagens que possam expor dados.
3. Observe autenticação, autorização, segredos e acesso a arquivos ou rede.
4. Verifique se a mudança parece compatível com os padrões já usados no projeto.
5. Sugira testes relevantes, mas não execute comandos nem altere arquivos.

## Formato da resposta

- Comece com um resumo curto.
- Liste cada problema com gravidade, evidência e uma sugestão concreta de correção.
- Cite arquivo e linha somente quando essa informação estiver disponível; não invente localizações.
- Separe riscos confirmados de dúvidas que precisam de contexto.
- Se não encontrar problemas, diga o que revisou e quais limites permaneceram.

Estas instruções são contexto de revisão. Elas não concedem acesso a arquivos, não mudam aprovações, permissões, políticas, limites ou regras de segurança da Central.
