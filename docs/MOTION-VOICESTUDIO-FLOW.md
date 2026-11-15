# Fluxo do mini episódio na Central

1. O usuário descreve o tema no chat do AI Motion Studio. Os trabalhadores criam um roteiro com oito cenas, a direção visual e as falas do narrador.
2. O motor de imagem cria uma imagem mestra do personagem e uma referência própria para cada cena. A Central verifica se os quadros são distintos e permite revisar a identidade visual antes da animação.
3. O motor de vídeo anima cada referência. Cada MP4 entra em sequência na trilha de vídeo, com a legenda planejada na trilha de texto.
4. Quando todas as falas pertencem ao narrador, a Central usa o perfil local “Minha voz” do OmniVoice no VoiceStudio para produzir uma narração contínua. Ela entra como um único clipe na trilha de áudio, do início ao fim do episódio. Falas de outros personagens continuam usando seus perfis por cena.
5. A Central monta o MP4 com FFmpeg, verifica o resultado com ffprobe e apresenta a prévia. O usuário pode dar play, pausar, buscar um ponto, aprovar ou refazer uma cena. Depois de alterar texto ou voz, “Refazer narração” atualiza a faixa; “Atualizar MP4 final” refaz a montagem.

O perfil de voz pode ser escolhido na revisão da cena. Uma gravação WAV PCM de 3 a 20 segundos, com a transcrição exata, pode criar outro perfil local. O VoiceStudio precisa estar disponível na máquina para a narração OmniVoice. O projeto, as referências, os vídeos e os downloads continuam armazenados na Central. O áudio da narração é salvo no armazenamento autorizado do usuário e a exportação rejeita um áudio desatualizado em relação ao roteiro.

O fluxo automático depende de oito vídeos e da duração suficiente para caber a narração. Se a voz exceder o tempo do episódio, a Central pede ajuste do texto ou das cenas e preserva os vídeos já produzidos. A qualidade da voz e a sincronização da ação devem ser revistas na prévia; este fluxo não equivale a sincronização labial automática.
