# Central IA — interface orientada por comandos / e Liquid Glass

## Origem visual

**O arquivo TSX enviado é a fonte de verdade visual** para os ícones,
a paleta Ice White e a geometria da tela inicial. Copiamos seus SVGs
CentralCore/OpenAI/Claude/Gemini/DeepSeek/Meta/Mistral para ReferenceIcons.jsx,
sem copiar os fluxos fictícios de execução. A refração React permanece uma
camada visual, sem modificar conteúdo de mensagens.
A refração usa a dependência MIT
[PallavAg/liquid-glass-web-react](https://github.com/PallavAg/liquid-glass-web-react)
na versão fixada no package-lock. Crédito ao autor do pacote; não copiamos
a implementação da biblioteca para o repositório.

**Nota:** expo-glass-effect é específico do React Native/iOS 26+ e não
funciona como componente nativo em React para Web/Electron. A Central usa a
biblioteca compatível com navegadores.

## Mudanças funcionais

- Chat continua como tela principal; menu lateral permanece para acessibilidade
  e compatibilidade com a navegação por mouse.
- Botão de estrela na barra insere "/" e abre a paleta real. Também funciona
  digitando "/" diretamente; / fora de um campo ou Ctrl+K (Cmd+K no macOS)
  também foca a paleta. ↑ ↓ selecionam, Enter executa, Escape fecha.
- Comandos de navegação e ferramentas apenas chamam funções existentes:
  /chat, /novo, /previa, /memoria, /computador, /agentes, /provedores,
  /projetos, /fluxos, /monitoramento, /tokens, /integracoes, /github,
  /automatico, /equipe e /configuracoes.
- /skills, /plugins, /skill ativar e /plugin ativar continuam pelo fluxo
  protegido de escopos e confirmações. /aprovar e /rejeitar continuam usando
  a operação original sobre uma etapa pendente.
- O orbe exibe os quatro símbolos da **referência** nas mesmas posições:
  OpenAI, Claude, Gemini e DeepSeek, mesmo quando não conectados. Os tooltips
  consultam a lista real de provedores habilitados. O menu lateral exibe os seis
  SVGs fornecidos no TSX, com estado de conexão real. Ícones e animações NÃO
  significam que um modelo esteja online ou processando.
- Barra Ice White em formato de pílula, estrela laranja, botão Enviar redondo
  #0f172a e menu hover de vidro, conforme o TSX. Anexos e controles de
  autonomia ficam em Ferramentas e permissões; aprovações permanecem visíveis.
- Barra de entrada e item selecionado da paleta recebem um fundo refrativo,
  enquanto texto, botões e diff de aprovações ficam nítidos.
- Acessibilidade: tecla Enter, Escape, setas, foco, contraste com fallback,
  prefers-reduced-motion, design responsivo.

## Garantia de regressão

A refatoração é apenas de React/CSS. Não altera API, DB, agent engine, segurança,
migrações, permissões ou conteúdo dos projetos. O chat segue usando EventSource,
aprovações, botões Parar e os mesmos endpoints reais.

## Checklist de aceitação visual antes do merge

- [ ] npm ci, npm test e npm run build em Windows e Ubuntu.
- [ ] Playwright ou Chrome DevTools: menu / aberto pelo ícone e pelo teclado,
  navegação ↑ ↓, Enter, Escape, clique e navegação real de páginas.
- [ ] Comparar screenshot lado a lado com o TSX de referência, especialmente
  fundo #f0f4f8, núcleo 180px, órbita 320px, cores de marcas e pill de input.
- [ ] Layout 390px e 1440px: sem overflow horizontal, composer acessível,
  aprovações e Parar visíveis mesmo com painel de execução aberto.
- [ ] Safari/Firefox/Edge: refração ou fallback sem sacrificar legibilidade.
- [ ] prefers-reduced-motion: orbe e gloss sem animação contínua.
- [ ] /skills e /plugins funcionam sem ativação global silenciosa.
- [ ] /aprovar e /rejeitar só operam com etapa pendente; autonomia desligada
  não se liga ao passar o mouse ou selecionar comandos.
- [ ] Verificar renderização no pacote Electron Desktop e na Web.

Não declarar conformidade visual completa sem capturas e testes reais em
navegador. Esta PR será testada sem alterar o estado do servidor principal.

Os ícones de comandos seguem as formas SVG Lucide (https://lucide.dev),
com licença ISC; o código de referência já utilizava lucide-react.

## Correção de contraste do vidro no tema claro (captura do operador)

A captura mostrou a barra sem distinção suficiente do fundo: borda branca
sobre branco-gelo e pouca refração perceptível. O CSS agora usa bordas
slate (rgba(43,57,79,.72), com hover/foco mais escuro), tonalidade azul-prata
translúcida, sombra de profundidade, brilho interno nas bordas e
`backdrop-filter` no fundo real. A camada React `LiquidGlass` mantém o
mapa de deslocamento de pixels **no conteúdo pintado pela própria lente**;
não afirmar que refrata os pixels arbitrários de toda a página.

A intensidade do compositor é específica, não global: força 0.14, banda 14,
brilho 0.24 e destaque na borda 0.52. Inputs e botões ficam fora da
camada decorativa, com eventos de mouse preservados. Tema escuro,
preferência por movimento reduzido e alto contraste mantêm fallback.

Referência analisada: https://github.com/rit3zh/expo-liquid-glass-view
(MIT). **Não instalada**: o README confirma iOS nativo apenas, com
Android/Web em `View` simples sem o renderer liquid glass. O comportamento
visual foi interpretado para a tecnologia existente React Web/Electron.

Testes adicionados: `frontend/src/glassComposer.test.mjs`. Eles verificam
cores, seletores, parâmetros da lente e acessibilidade estática. A
fidelidade **ainda exige captura de navegador e teste manual de foco**.

## Revisao integrada em Windows e Chromium

A revisao em checkout isolado preservou o desenho que ja existia nesta branch e corrigiu superficies escuras antigas de campos, dialogos e paineis para usarem os tokens de tema. A consulta real de catalogos, permissoes e delegacao continua ligada aos endpoints existentes. O compositor agora cresce com o texto, nao exibe redimensionador nativo e usa foco na capsula em vez de um retangulo sobre a entrada.

Navegador real: cadastro de conta descartavel, abertura de comandos, navegacao por /provedores e confirmacao de campo branco com texto slate. Nenhuma chave de producao foi usada para o teste visual. O browser-act foi utilizado em navegador dedicado; a sessao foi encerrada.

A validacao Electron cobre Ctrl+K, setas, Escape, Enter, lista de comandos real, layout de 390px sem overflow horizontal, troca de tema e paleta clara dos controles. As validacoes restantes de Windows e o hash do pacote ficam no relatorio desktop correspondente. Nao se afirma homologacao em Safari, Firefox, Ubuntu ou iOS.
