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

A versão inicial usa `POST /v1/audio/speech`, `GET /v1/audio/voices` e `GET /health`. O recurso de clonagem utiliza perfis criados no VoiceStudio, inclusive pela nova seção de importação de WAV na Central. Use apenas vozes próprias ou autorizadas; o adaptador aceita perfil por ID.


## Evolução: expressividade, textos longos e identidade vocal

A implementação foi conferida também contra o código do VoiceStudio **v0.5.7**, a versão instalada no computador de teste. Essa versão oferece \`POST /profiles\` (com \`name\`, \`ref_audio\`, \`ref_text\`, \`kind=clone\`) e \`GET /v1/audio/voices\`.

### 1. Expressividade de suspense

- No menu **Voice Studio → Trecho natural**, gere uma primeira amostra com voz Padrão, velocidade 1,0×, 32 passos e seed 42.
- Clique **Trecho com pausas**, mantendo os demais parâmetros. Compare as pausas de 500–900 ms após os momentos-chave.
- A API compatível \`/v1/audio/speech\` envia o texto diretamente ao motor; para evitar que ele leia \`[pause 700ms]\` em voz alta, **a Central interpreta esses marcadores**, gera os trechos separadamente e insere silêncio PCM exato antes de montar o WAV.
- Pausas aceitas: \`[pause]\` (350 ms), \`[pause 500ms]\` e \`[pause 1s]\`, de 100 ms até 10 segundos. Trechos longos recebem uma separação suave de 180 ms entre blocos.
- **Suspense** não é uma emoção graduada do OmniVoice. O estilo usa pontuação e pausas; a opção **Sussurrada** envia somente a tag de estilo \`whisper\`, aceita pelo vocabulário fechado do motor, e deve ser avaliada separadamente.

### 2. Consistência em 1–2 minutos

Clique **Roteiro longo (1–2 min)** e gere com o mesmo perfil. O texto foi escrito para investigar se a voz permanece coerente em frases longas, transições, números e encerramento de suspense. O tempo varia com velocidade, pausas e hardware.

O backend limita cada trecho a **650 caracteres** e compõe os WAVs de modo sequencial, mantendo perfil, velocidade, seed e refinamento em todas as chamadas. Cada trecho usa a mesma referência de voz; **a identidade tende a ser mais estável, mas cortes e diferenças de entonação nas junções continuam possíveis**. A UI registra o tempo real de renderização e a duração do áudio após o carregamento.

### 3. Salvar a voz da sua amostra

O perfil é uma **referência de áudio**, e não um identificador mágico da voz que o modelo geraria no modo Padrão. Para reutilizar a mesma identidade:

1. Escolha uma amostra curta gerada no painel e clique **Usar como referência de voz**. Ou importe o WAV do teste anterior (por exemplo \`Downloads\\teste-voz.wav\`).
2. Informe um **nome de perfil** e transcreva exatamente o que é falado no arquivo, sem as marcações de pausa.
3. Clique **Salvar perfil no VoiceStudio**. O backend valida o upload WAV PCM e a duração de **3 a 20 segundos**; então encaminha a referência por multipart para a instalação local do VoiceStudio, que persiste o perfil.
4. O perfil recém-criado aparecerá no seletor de voz da Central. Escolha-o para as amostras seguintes. Reabra o painel e confirme que ele permanece listado.

As vozes ficam persistidas **no armazenamento do VoiceStudio**, não na base de dados da Central, não no GitHub e não no histórico de takes em memória do navegador. Se o serviço VoiceStudio for reinstalado com um diretório de dados diferente, a lista poderá desaparecer; mantenha backups dos dados do VoiceStudio. **O armazenamento de perfis é compartilhado por todos os usuários que usem a mesma instância do serviço**; a funcionalidade é voltada inicialmente ao uso pessoal.

Não publique WAVs pessoais em repositórios. Somente salve referências com os direitos/consentimentos necessários.

### Atualizar a branch de teste no Windows (CMD)

\`\`\`bat
cd /d C:\\Users\\marco\\central-voice-teste
git fetch origin feat/voicestudio-local-prototype
git switch feat/voicestudio-local-prototype
git pull --ff-only
.venv\\Scripts\\python.exe -m pytest tests\\test_voice_studio.py -q
npm run build
\`\`\`

Com VoiceStudio ativo em \`http://127.0.0.1:3900\`, execute novamente a Central de testes na porta 8876 conforme instruções anteriores. Não mescle esta PR à main antes de conferir os testes automatizados e ouvir as três novas narrações.

#### Limitações

- A geração de um texto de 1–2 min pode demorar mais que o comprimento final do áudio, pois vários trechos usam a mesma GPU sequencialmente.
- A qualidade emocional e a fidelidade à voz ainda devem ser conferidas **ouvindo o WAV produzido na máquina do usuário**. Esses testes não são executados apenas por criar commits no GitHub.
- O perfil importa uma referência curta; a função não armazena todas as amostras da sessão nem oferece edição de perfis, exclusão ou histórico persistente.

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

A integração não armazena áudio ou credenciais no banco da Central, não transcreve e não provisiona automaticamente o VoiceStudio. Os perfis são persistidos no armazenamento próprio do VoiceStudio. Testes de áudio end-to-end e avaliação subjetiva dependem de um serviço rodando no computador de destino.
