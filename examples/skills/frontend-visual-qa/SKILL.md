---
name: frontend-visual-qa
description: Refinar interfaces web e revisar sua entrega visual real, incluindo responsividade e interacoes, sem confundir build aprovado com design aprovado.
---

# Entrega visual de interfaces

Aplique quando estiver implementando ou revisando uma interface web. Preserve o brief, a identidade escolhida e o workspace autorizado. Nao reinicie um projeto funcional sem motivo.

## Antes de desenhar

Confirme o entrypoint servido ao navegador. Arquivos App.jsx e App.tsx com mesmo nome podem fazer desenvolvimento e build carregarem implementacoes diferentes: use import explicito quando necessario. Confira a versao e a entrada real do CSS; classes presentes no JSX nao comprovam que o CSS foi gerado. Leia os arquivos antes de alterar e use os hashes retornados pelas ferramentas.

## Direcao e acabamento

Defina uma hierarquia clara: mensagem principal, apoio curto, CTA primario e secundario. Use escala tipografica coerente, largura de leitura limitada, alinhamentos e espacamento consistentes. Preserve contraste legivel; brilhos e gradientes devem apoiar o conteudo. Elementos decorativos nao podem cobrir texto ou interceptar cliques.

Em sites de portfolio ou agencia, areas de projetos precisam de composicoes visuais relevantes, como mockups originais em CSS/SVG, em vez de grandes retangulos vazios. Identifique projetos ficticios como conceitos. Nao invente clientes, depoimentos, premios ou numeros comerciais.

Menu mobile deve abrir navegacao real, informar aria-expanded/aria-controls, ter nome acessivel e fechar ao escolher um link. Formularios precisam de labels associadas, validacao e feedback inline. Sem backend, apresente uma demonstracao honesta: nunca diga que enviou email. Ofereca foco visivel, espaco sob header fixo nas ancoras e prefers-reduced-motion.

## Evidencias de entrega

Verifique o layout amplo e estreito (por exemplo 1440 e 390 pixels): todas as secoes, titulo e CTA visiveis, nenhuma sobreposicao, corte de texto ou rolagem horizontal. Teste os links, menu e estados do formulario, inclusive erro e sucesso demonstrativo. Corrija defeitos concretos antes de polir efeitos.

Execute o build/testes existentes apos a ultima alteracao. Quando DevTools estiver ativo, use as ferramentas locais aprovadas para snapshot, console e Lighthouse. Nao repita auditorias sem nova alteracao ou motivo registrado.

Build e Lighthouse nao medem beleza. So declare revisao visual aprovada se uma imagem renderizada foi realmente examinada. Se voce so recebeu texto/DOM, informe essa limitacao e aguarde a avaliacao visual do supervisor. Diferencie funcionalidades verificadas, observacoes visuais e pendencias. Uma captura bonita tambem nao substitui testes de interacao.
