# Central IA — interface orientada por comandos / e Liquid Glass

## Origem visual

Design inspirado no exemplo TSX enviado pelo operador, principalmente no
orbe central, itens de menu animados, composer único e comandos com "/".
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
- O orbe mostra somente os provedores habilitados carregados da API.
  Efeitos de animação NÃO significam que um modelo está online nem produzem
  eventos ou resultados simulados.
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
