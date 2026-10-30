# Central IA Web + Desktop Windows

## Estratégia

A versão Web permanece intacta: FastAPI + React, executada pelo run.py.
A versão Desktop reaproveita o MESMO frontend React e o MESMO backend FastAPI;
Electron apresenta a interface em uma janela e inicia um executável Python
empacotado com PyInstaller. Duas versões sem duplicar a lógica de negócio.

**Estado: MVP de empacotamento, não instalador final homologado.**
Ainda faltam ensaio de binário em Windows limpo, assinatura, prova de
atualização/rollback e distribuição oficial. Este primeiro alvo é Windows x64.

## O que entra no pacote (sem baixar na instalação)

- Aplicativo Electron, com seu navegador integrado.
- Build do frontend React servido pela própria Central.
- Python embutido, FastAPI e dependências importadas por PyInstaller.
- Banco SQLite, migrações, memória e recursos de agentes existentes.

Recursos opcionais NÃO estão incluídos neste primeiro pacote:
Ollama e modelos locais, Codex, Claude Code, Gemini CLI, OpenCode, ACP,
Chrome DevTools MCP, Playwright, Docker, VS Code, FFmpeg, WhisperX, Remotion,
ComfyUI/Wan, CUDA e drivers de vídeo. Precisam de instalador/configurador
posterior, com inspeção de licença, versão, tamanho, origem/hash e autorização.
Modelos e serviços podem exigir credenciais, assinatura paga ou muito disco.

## Diagnóstico inicial de dependências (leitura somente)

Na primeira abertura, o desktop apresenta um diálogo nativo com o catálogo
de ferramentas locais. Ele procura apenas nomes de arquivos executáveis
em pastas absolutas do PATH; **não executa** ferramentas externas, não testa
credenciais, não instala modelos e não pede privilégios de administrador.

- "Detectado no PATH" não comprova versão, licença, assinatura, compatibilidade
  com a Central ou disponibilidade de um modelo/servidor.
- Componentes como Chrome DevTools MCP, ACP, WhisperX, Playwright e ComfyUI
  são mostrados como **não verificados**, não como instalados.
- O operador pode abrir a Central sem instalar nada. A caixa "Não mostrar"
  controla apenas a reapresentação do aviso, e o diagnóstico permanece
  acessível pelo menu **Central IA → Verificar dependências opcionais**.
- Um assistente de instalação real, com hashes, origem, licença, espaço,
  aprovação e rollback, é uma próxima fase; não faz parte deste piloto.

## Dados e segurança

- Desktop reserva socket na interface 127.0.0.1 com porta dinâmica.
- Web continua usando a porta configurável 8765.
- Banco de dados desktop fica no diretório de dados do Electron por usuário,
  isolado do banco da versão web. Nenhuma migração automática de dados web.
- Não há desabilitação de login, nem concessão automática de acesso ao PC.
- Janela usa contextIsolation, sandbox, sem Node no renderer; popups,
  permissões, navegação e requisições fora da origem local são bloqueados.
- Um serviço local ainda pode ser atacado por software instalado no mesmo
  computador; a autorização do backend permanece essencial.
- O instalador não executa downloads de IA automaticamente.

## Preparar o instalador piloto em uma máquina Windows de desenvolvimento

1. Faça checkout desta branch em uma cópia de homologação, não sobre
   seu ambiente principal com banco de dados ativo.
2. Garanta Python 3.11+ com venv .venv, Node.js/npm e acesso à rede para
   instalar as ferramentas de BUILD. Verifique o script antes de executá-lo.
3. Execute na raiz do repositório:

    .\desktop\build_windows.ps1

4. A saída, se a construção for aprovada, ficará na pasta
   desktop/dist-installer. Esta versão não é assinada, portanto não
   publique nem distribua como instalador confiável.

Este script de build instala ferramentas de desenvolvimento e
empacotamento na máquina do programador. O instalador entregue ao
usuário final não precisará rodar pip/npm para abrir a Central.

## Testes que bloqueiam uma distribuição oficial

- CI de Python+frontend em Windows e Ubuntu; sintaxe da janela Electron.
- Construir binário PyInstaller em Windows e executar health check local.
  O CI testa agora GET /api/health/ready e GET / usando o executável empacotado.
- Gerar instalador NSIS e testar em VM Windows limpa sem Python/Node.
- Executar Desktop e Web simultaneamente sem conflito de porta/banco.
- Criar conta, projetos, agentes, testes, prévia, aprovações e persistência.
- Desinstalar sem destruir dados sem aviso; backup e recuperação da chave.
- Assinatura digital, SmartScreen, updater autenticado, SBOM e versões
  de Electron/Python/Node com lockfile auditado.
- Revisar comportamento de OAuth externo e prévias de projetos no desktop.

## Próxima fase

Assistente de primeiro uso: verificar dependências e espaço disponível;
instalar apenas recursos opcionais selecionados pelo operador com URL, hash,
versão, EULA/licença, necessidades de GPU e aprovação clara. Exibir estado
de cada componente e permitir desinstalação sem excluir projetos.

Documentação principal de empacotamento: PyInstaller + Electron Builder.
