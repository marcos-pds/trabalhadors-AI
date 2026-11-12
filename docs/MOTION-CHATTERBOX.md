# Vozes locais do Motion Studio

O Motion Studio usa o modelo Chatterbox ajustado para português brasileiro diretamente em um processo Python isolado da Central. Não precisa do aplicativo VoiceStudio para gerar falas. Cada conta guarda referências WAV e IDs de voz em `data/motion-studio/voices/chatterbox/<user-id>/`. O projeto guarda somente os IDs; WAVs narrados e legendas continuam nos artefatos do episódio.

## Instalação no Windows com NVIDIA

Execute `scripts/install_motion_chatterbox.ps1` na raiz do repositório. O script instala Python 3.11 isolado, PyTorch CUDA, o código oficial e os pesos de `ResembleAI/Chatterbox-Multilingual-pt-br` em `data/motion-studio/`. O download dos dois checkpoints ocupa cerca de 3,2 GB e pode demorar. O script verifica os SHA256 publicados pelo provedor. A interface indica se o ambiente está instalado. O modelo usa a GPU local e pode disputar memória com Wan/ComfyUI; gere as vozes antes das cenas quando necessário.

O repositório e o modelo são MIT. O checkpoint específico para pt-BR continua usando `language_id="pt"`, com voz de referência por personagem.

## Fluxo

1. Entre na Central e abra o Motion Studio.
2. Importe uma referência WAV mono PCM16 de 3 a 30 segundos, com fala limpa e consentimento da pessoa retratada.
3. Escolha um perfil para cada personagem e clique em **Ouvir**.
4. Gere o episódio. Todas as falas são processadas em um único trabalho local; a Central encaixa cada uma no tempo do roteiro e salva um WAV de 48 kHz mais as legendas.

O VoiceStudio permanece disponível apenas como motor legado para episódios antigos. A reprodução dos WAVs e MP4s salvos independe de ambos os motores.

## Fala por cena

No Motion Studio, preencha **Fala da cena** e escolha o personagem antes de gerar uma cena Wan ou LTX. A Central usa a voz vinculada ao personagem, gera um WAV e uma legenda JSON na pasta do projeto, e adiciona a fala à trilha de áudio quando o vídeo fica pronto. Cenas sem fala continuam silenciosas. A fala precisa caber na duração da cena; nesse caso, a Central informa quando é necessário encurtá-la ou dividi-la.

Para uma cena que já tem vídeo, selecione o clipe e use **Gerar fala para cena selecionada**. Isso gera uma nova tomada na trilha de áudio sem refazer o MP4. O WAV é acessível apenas ao dono e seu hash é conferido antes da prévia e do download.

O preview reproduz o WAV junto com o vídeo e acompanha pausa, busca e passagem para a próxima cena. O MP4 individual gerado pelo modelo continua sendo o artefato visual; o WAV fica disponível separadamente para download e edição.

No Windows, o instalador guarda também a Python base do Chatterbox em `data/motion-studio/python311-base`, para que a Central consiga iniciar o motor de voz mesmo quando está executando em outra versão do Python.
