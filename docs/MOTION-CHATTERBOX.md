# Vozes locais do Motion Studio

O Motion Studio usa o Chatterbox Multilingual V3 diretamente em um processo Python isolado da Central. Não precisa do aplicativo VoiceStudio para gerar falas. Cada conta guarda referências WAV e IDs de voz em `data/motion-studio/voices/chatterbox/<user-id>/`. O projeto guarda somente os IDs; WAVs narrados e legendas continuam nos artefatos do episódio.

## Instalação no Windows com NVIDIA

Execute `scripts/install_motion_chatterbox.ps1` na raiz do repositório. O script instala Python 3.11 isolado, a revisão oficial do Chatterbox com suporte ao V3 e PyTorch CUDA na pasta `data/motion-studio/chatterbox-runtime/`. A primeira geração baixa os pesos oficiais de `ResembleAI/chatterbox` e pode demorar. A interface indica se o ambiente está instalado. O modelo usa a GPU local e pode disputar memória com Wan/ComfyUI; gere as vozes antes das cenas quando necessário.

O repositório e o modelo são MIT. Para português brasileiro, o V3 geral usa `language_id="pt"`; o checkpoint específico `pt-BR` é uma possível evolução depois de validar o V3 geral.

## Fluxo

1. Entre na Central e abra o Motion Studio.
2. Importe uma referência WAV mono PCM16 de 3 a 30 segundos, com fala limpa e consentimento da pessoa retratada.
3. Escolha um perfil para cada personagem e clique em **Ouvir**.
4. Gere o episódio. Todas as falas são processadas em um único trabalho local; a Central encaixa cada uma no tempo do roteiro e salva um WAV de 48 kHz mais as legendas.

O VoiceStudio permanece disponível apenas como motor legado para episódios antigos. A reprodução dos WAVs e MP4s salvos independe de ambos os motores.
