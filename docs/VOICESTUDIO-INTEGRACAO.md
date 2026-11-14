# Voice Studio local — protótipo da Central AI

Este módulo integra a Central (React + FastAPI) ao serviço **externo** [VoiceStudio](https://github.com/debpalash/VoiceStudio) por uma API de áudio. Ele **não incorpora** o código AGPL do VoiceStudio à Central.

## Iniciar o serviço de voz

Siga a [instalação oficial do VoiceStudio](https://github.com/debpalash/VoiceStudio/tree/main/docs/install) para o seu sistema e hardware. A documentação oficial descreve o modo servidor em [production-private-api.md](https://github.com/debpalash/VoiceStudio/blob/main/docs/production-private-api.md).

Exemplo Linux/Docker (imagem fixada indicada no documento upstream consultado):

```bash
docker run --rm --name voicestudio -p 127.0.0.1:3900:3900 \
  -v voicestudio-data:/app/omnivoice_data \
  -v voicestudio-models:/app/omnivoice_data/huggingface \
  ghcr.io/debpalash/voicestudio:0.5.6
```

A imagem e as instruções acima são **referência**, não foram testadas neste repositório. A instalação completa pode exigir download de modelos grandes; confira a versão de imagem, drivers e licenças do motor antes de executar. Em computadores Windows sem Docker, use a instalação nativa/servidor do VoiceStudio conforme o guia oficial. Não exponha a porta 3900 à internet.

No ambiente onde a **Central FastAPI** é iniciada, configure:

```dotenv
CENTRAL_VOICESTUDIO_URL=http://127.0.0.1:3900
# Opcional em modo local; obrigatório se exigir autenticação entre serviços.
CENTRAL_VOICESTUDIO_API_KEY=
```

Se o backend da Central rodar em outro container, `127.0.0.1` apontará para o container da Central; configure uma rede privada entre serviços e `CENTRAL_VOICESTUDIO_URL=http://voicestudio:3900` (nome interno do serviço). Não exponha sua chave ao React ou ao repositório.

## Testes

```bash
python -m pytest tests/test_voice_studio.py -q
npm test
npm run build
```

Estes testes verificam o contrato de integração com respostas simuladas. Para um **teste real**, inicie ambos os serviços e faça login na Central. Abra **Voice Studio** no menu lateral e confirme que o indicador mostra "Motor conectado".

1. Gere um mesmo texto de aproximadamente 150 caracteres em **Natural**, velocidade 1,0×, 32 passos.
2. Gere novamente em **Suspense**, mantendo voz e texto.
3. Experimente 16, 32 e 48 passos; compare tempo de geração e artefatos de áudio.
4. Teste um texto com números, nomes brasileiros, pontuação e pausas, mantendo o idioma `pt`.
5. Ouça as amostras com fones, escolha a que preservar melhor pronúncia, timbre, pausas e naturalidade.
6. Faça download dos WAVs de referência. As amostras no navegador **não são persistidas**.

A versão inicial usa `POST /v1/audio/speech`, `GET /v1/audio/voices` e `GET /health`. O recurso de clonagem utiliza **perfis previamente criados no VoiceStudio**: use apenas sua própria voz ou áudio para o qual tenha permissão. O adaptador aceita perfil por ID.

## Critérios de qualidade para decidir o motor

- **Pronúncia PT-BR**: números, siglas, palavras acentuadas, nomes próprios.
- **Naturalidade e expressividade**: ritmo, pausas, entonação, preservação da intenção.
- **Consistência**: manter a mesma voz em várias sentenças e tomadas.
- **Tempo de renderização**: registrar segundos para uma amostra com o mesmo texto e parâmetros.
- **Confiabilidade**: erros claros quando o motor está offline, sem gravações vazias.

**Importante**: instruções de estilo podem não ser respeitadas integralmente pelo OmniVoice, especialmente fora do conjunto de atributos do modelo. A API aceita esse campo, mas a melhor forma de alcançar uma voz expressiva pode exigir testes de outro motor, como VoxCPM2 ou IndexTTS, e não apenas aumentar os passos.

## Arquivos envolvidos

- `central/voice_studio.py` — adaptador FastAPI protegido por sessão + CSRF, com URL controlada por variável de ambiente e áudio limitado a 30 MB.
- `central/main.py` — registro das rotas.
- `frontend/src/VoiceStudioPanel.jsx` — editor, seleção de perfil, qualidade e comparação de amostras.
- `frontend/src/App.jsx` — navegação e montagem do painel.
- `tests/test_voice_studio.py` — testes de contrato isolados do motor.

A versão inicial não armazena áudio ou credenciais no banco da Central, não transcreve e não provisiona automaticamente o VoiceStudio. Testes de áudio end-to-end e avaliação subjetiva dependem de um serviço rodando no computador de destino.
