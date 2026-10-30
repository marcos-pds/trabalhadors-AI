# Interpretação de pedidos — política 2

A Central interpreta a intenção antes de selecionar trabalhadores. Esta política
encaminha tarefas; a autorização da pasta e as permissões das ferramentas continuam
sendo verificadas separadamente.

## Exemplos

| Pedido | Comportamento esperado |
| --- | --- |
| “Altere o título para Minha empresa” | Edição real, conferência do texto salvo e build |
| “Deixa o botão maior” | Implementação e revisão |
| “Quero o fundo azul” | Implementação e revisão |
| “Pode corrigir o formulário?” | Pedido de implementação |
| “Ajuste `src/App.tsx`” | Inspeção e edição do arquivo no workspace autorizado |
| “Não mude o layout, mas corrija o botão” | Correção, preservando o layout |
| “Diagnostique o formulário” | Consulta real do projeto, sem exigir alterações |
| “Como corrigir o formulário?” | Explicação |
| “Faça um prompt para melhorar o site” | Produção de prompt |
| “Continue” | Recupera a última implementação da mesma conversa, se houver |
| “Deixe maior” | Recupera o alvo da mesma conversa; ambiguidade exige esclarecimento |

## Cobertura e limites

- Vocabulário de criação, correção, aparência, tamanho, alinhamento, navegação,
  formulários, configurações e remoção/ocultação de elementos.
- Formas coloquiais, perguntas que expressam um pedido e menções a arquivos.
- Preservação de negações, instruções de somente leitura, exemplos citados e código
  entre cercas Markdown. Limites de escopo como “não altere arquivos fora do
  workspace” não impedem a edição solicitada dentro da pasta.
- Separação entre revisão conceitual e inspeção de material concreto do projeto.
- Pedidos com várias alterações não são tratados como um único texto literal.
- `task_classified` registra `policy_version=2` e `interpretation_reason`.

As regras cobrem padrões comuns de linguagem; não garantem compreender qualquer
frase ambígua. As verificações de entrega continuam exigindo ações e validações reais.

## Verificação

111 novos casos em `tests/test_intent_interpretation.py`, incluindo positivos,
negações, perguntas, instruções mistas e isolamento de contexto entre conversas.
Suíte completa: 597 aprovados, 26 ignorados, dois avisos existentes.
