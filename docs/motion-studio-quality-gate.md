# Motion Studio: identidade e narração

## Piloto de 11/11/2026

- Referência: `snapinsta-1794365777712.mp4`, 84,70 s, 720 × 1280. O personagem ilustrado mantém cabelo, fone, uniforme e proporções nas amostras de cenários diferentes. A narração tem continuidade entre cenas.
- Episódio Caio anterior: oito cenas, 29,67 s. As falas curtas deixavam aproximadamente 0,8 a 2,4 s de silêncio no final de várias cenas. Roupa, óculos e rosto de Caio mudavam nas cenas finais.
- O IP-Adapter SDXL com peso 0,85 recuperou melhor o jaleco na nova imagem da cena 6, mas transformou os óculos em boné e alterou o rosto. A imagem e o vídeo dessa cena continuam em revisão. Aumentar apenas o peso do adaptador não resolve a identidade.
- Teste de voz: o perfil Qwen Base `Caio · Brasil (teste)` gerou uma fala de 3,28 s para a primeira cena. O novo vídeo reservou 4,08 s e substituiu somente a cena 1; a voz, a legenda e o MP4 foram atualizados na Central. As demais cenas continuam com as vozes anteriores.

## Critério de aprovação

1. Fixar uma imagem mestra e uma ficha de personagem com frente, perfil e corpo inteiro, aprovadas visualmente.
2. Cada quadro deve manter rosto, cabelo, acessório e figurino, e mostrar o cenário e a ação previstos. Uma falha bloqueia a animação dessa cena; não basta comparar se dois quadros são diferentes.
3. Ouvir a voz em português brasileiro em uma tomada de 10 a 15 s. Conferir inteligibilidade, sotaque, entonação e pausas antes de produzir o episódio.
4. Medir duração da fala antes da animação; reservar tempo suficiente no vídeo. Conferir a ausência de lacunas e sobreposições na timeline e no MP4 exportado.
5. Aprovar cenas individualmente. A exportação de teste não equivale à aprovação editorial.

## Próxima abordagem visual

O adaptador de imagem única serve para exploração, mas não garante personagem idêntico. O próximo experimento deve comparar um **modelo do personagem com poses aprovadas** (ficha de personagem e edição por máscara/controle de pose) com a geração SDXL atual, usando os mesmos cenários e avaliando lado a lado. A identidade do personagem deve ser tratada separadamente do cenário; só depois um quadro aprovado segue para o motor de vídeo. Se ainda houver troca de rosto ou figurino, considerar um personagem 2D em camadas ou um modelo ajustado especificamente para ele.

## Próxima abordagem de voz

Gerar uma narração contínua com uma única voz brasileira autorizada e dividir o áudio por marcas de tempo das cenas, em vez de sintetizar oito frases isoladas. Testar primeiro duas cenas com variação de emoção e medir as pausas. A amostra do Reel é referência de ritmo e acabamento, não uma voz a copiar.

## Piloto controlado de duas tomadas

- A ficha visual de Caio foi gerada a partir da imagem mestra, com frente, três quartos e perfil. Dois quadros consecutivos foram criados com a ficha e o primeiro quadro como referências. Rosto, óculos, cabelo, jaleco e paleta permaneceram reconhecíveis nos quadros estáticos.
- A narração foi sintetizada uma única vez pelo Qwen Base com o perfil brasileiro de Caio. Duração: 8,56 s. A análise de silêncio detectou apenas duas pausas internas de 0,39 s e 0,50 s; não houve os intervalos de 1 a 2 s entre falas do episódio anterior.
- O LTX local foi testado nas duas imagens com 49 quadros a 12 fps. Na primeira tomada ele ampliou o rosto e mudou o braço de forma brusca. Na segunda, o anel de energia e o recuo apareceram, mas os braços ainda oscilaram.
- O MP4 de comparação usa movimento de câmera controlado sobre o primeiro quadro e a segunda tomada LTX, com corte direto, legendas e áudio contínuo. Duração: 8,56 s, H.264 720 × 1280 a 24 fps e AAC. Arquivo local: `work/caio-two-shot-pilot/caio-two-shot-controlled.mp4`.
- Este piloto usa geração de imagens e montagem locais fora do fluxo automático do Motion Studio. Demonstra que referências múltiplas e narração contínua ajudam, mas **não prova** que a Central já produz esse resultado com um único prompt. A integração e a avaliação auditiva pelo usuário continuam pendentes.

Fontes técnicas: [IP-Adapter Plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus), [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), [requisitos do Fish Audio S2-Pro](https://speech.fish.audio/install/). O S2-Pro oficial recomenda 24 GB de VRAM; a RTX 3060 local tem 12 GB, portanto não é o próximo teste local prioritário.
