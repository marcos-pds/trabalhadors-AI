# Guia de instalação e primeiro uso — Windows

**Central de Trabalhadores IA — versão de consolidação**

- Origem: https://github.com/marcos-pds/trabalhadors-AI
- Referência usada neste pacote: branch `chore/consolidacao-central-20261028`
- Criador e mantenedor: Marcos Paulo — [@marcos-pds](https://github.com/marcos-pds)
- Estado: **versão de homologação**, não release de produção

## 1. Antes de instalar

Instale Python 3.11+ e Node.js 20+ (recomenda-se 22 para a aplicação), com npm, a partir dos sites oficiais. Reserve espaço para dependências e projetos. No PowerShell:

```powershell
py -3 --version
node --version
npm --version
```

Baixe o ZIP da branch oficial pelo GitHub e extraia **em uma pasta nova**, por exemplo `C:\Projetos\Central-IA\central-ia-consolidada`. Não descompacte sobre a instalação anterior; isso protegerá seu banco, chaves e checkpoints.

**Credenciais:** o ZIP de código-fonte do GitHub traz arquivos versionados, não os dados locais ignorados pelo Git. **Não copie** `data/`, `secret.key`, `.env`, arquivos de tokens nem pastas `.venv` de outra instalação. A instalação nova gera sua própria chave em `data/secret.key`.

## 2. Instalar dependências e construir a interface

Abra o PowerShell dentro da pasta extraída, a que contém `run.py`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
npm run build
```

Alternativa: execute `iniciar_windows.bat` para preparar dependências e iniciar, **mas primeiro confira que a porta 8765 está livre**.

## 3. Iniciar sem conflitar com a Central existente

Se já usa a Central original em `8765`, abra a cópia nova em `8876`:

```powershell
$env:CENTRAL_HOST = "127.0.0.1"
$env:CENTRAL_PORT = "8876"
$env:CENTRAL_JOB_MODE = "embedded"
$env:CENTRAL_DATA_DIR = (Join-Path (Get-Location) "data")
Remove-Item Env:CENTRAL_SECRET_KEY -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe run.py
```

Abra http://127.0.0.1:8876 e crie **uma conta local nova** (não é necessário reutilizar a senha antiga). O novo `data/` terá um banco e uma chave próprios.

Para encerrar, pressione Ctrl+C no terminal que executa o servidor.

## 4. Configurar seu primeiro provedor

Na Central, abra **Provedores** e escolha um dos métodos existentes:
- **Ollama local**: instale o Ollama por meio do site oficial e baixe um modelo compatível; normalmente usa `http://127.0.0.1:11434`. Confira o identificador e rode o teste de conexão.
- **Codex CLI**: instale o Codex CLI pela documentação oficial, autentique-se normalmente e use a tela de runtimes/Provedores para detectar e conectar o Codex. A integração pode limitar versões do CLI; consulte `docs/EVOLUCAO-CODEX-ETAPAS.md`.
- **APIs externas**: configure explicitamente suas próprias chaves em Provedores, sem as colocar em arquivos versionados.

A instalação nova não vem conectada a contas ou modelos. Cotas, requisitos e autenticação são definidos pelo provedor.

## 5. Primeiro teste funcional

No chat da Central:

> Crie uma landing page responsiva chamada NovaTech AI com menu, hero, três cards de recursos, formulário de contato e rodapé. Separe o trabalho entre implementador e revisor. Salve todos os arquivos em um projeto novo, execute os testes, abra a prévia no navegador e me mostre a página funcionando.

Autorize apenas o workspace de teste e as ferramentas necessárias. A Central precisa que as permissões de escrita sejam concedidas para criar arquivos.

Peça, **na mesma conversa**:

> Altere o botão principal para verde, preserve o restante e valide a alteração na prévia.

Use o painel de execução para analisar arquivos gerados, testes, erros, cancelamentos e checkpoints. Nem todas as etapas de QA visual autônomo estão concluídas; não interprete uma resposta de texto como comprovação de entrega.

## 6. Testes da instalação

Em outro PowerShell, na pasta instalada:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm test
```

Em execução, cheque a API na porta configurada:

```powershell
Invoke-WebRequest http://127.0.0.1:8876 -UseBasicParsing | Select-Object StatusCode
```

Resultado HTTP esperado: `200`.

## 7. Solução de problemas

- **WinError 10048**: a porta está ocupada. Inspecione `Get-NetTCPConnection -LocalPort 8876 -State Listen` e o processo correspondente. Não encerre PIDs sem identificar o programa.
- **Dependência Python ausente**: use o executável de `.venv\Scripts\python.exe`, não Python global.
- **Interface antiga**: execute novamente `npm run build` e recarregue a página.
- **Credenciais ausentes**: esperado; instale e configure o provedor escolhido. Não copie chaves da instalação anterior.
- **Codex CLI incompatível**: verifique a versão documentada pela integração e sua autenticação.
- **Porta 8765 ocupada**: execute em `8876`.

## 8. Segurança e backup

Não exponha o serviço diretamente à internet. Mantenha o servidor em `127.0.0.1`. Depois de criar projetos e credenciais, faça backup privado de `data/` (incluindo `secret.key`), nunca o coloque em ZIP público. A chave da instalação é necessária para descriptografar segredos dessa instalação.

## 9. ZIP sem credenciais e confirmação de autoria

O ZIP oficial obtido do GitHub inclui somente arquivos rastreados no commit. Antes de distribuir, confirme que não há dados sensíveis em arquivos que alguém tenha commitado intencionalmente. O projeto traz [AUTORIA.md](AUTORIA.md) e a assinatura no [README.md](README.md), mas isto **não substitui** a verificação de licenças de terceiros ou a proteção legal da autoria.

Link para baixar o código-fonte desta branch:
https://github.com/marcos-pds/trabalhadors-AI/archive/refs/heads/chore/consolidacao-central-20261028.zip
