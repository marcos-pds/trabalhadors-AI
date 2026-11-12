# AI Resource Orchestrator — fases 1, 2, 3 e 4 (diagnóstico Ollama)

Inspiração técnica: [kimi-k3-in-c](https://github.com/FareedKhan-dev/kimi-k3-in-c), especialmente `docs/ARCHITECTURE.md` e `docs/TUNING.md`. Este módulo é implementação independente; não reproduz o motor de inferência K3 nem seus pesos.

## Implementado

- `central/resource_orchestrator.py`: gerenciador **cooperativo em um processo** de reservas declaradas de RAM, VRAM, armazenamento temporário e slots exclusivos de GPU, com prioridades 0–9, FIFO entre iguais, cancelamento, timeout e liberação idempotente.
- `plan_weight_placement`: recomendação matemática para manter pesos frequentes em GPU/RAM e marcar o restante como candidato a streaming **somente se o backend declarar compatibilidade**.
- `ResidentModelPlanner`: propostas LRU de liberação de modelos ociosos; nunca encerra processos ou descarrega pesos.
- `snapshot`: orçamento e uso declarado, sem expor prompts, caminhos ou credenciais.
- Testes unitários em `tests/test_resource_orchestrator.py`.

## Fase 2 — instrumentação e integração conservadora

- `central/resource_telemetry.py`: leitura física de RAM via `GlobalMemoryStatusEx` no Windows ou `MemAvailable` no Linux; VRAM das GPUs NVIDIA via `nvidia-smi` com tempo limite de 2 segundos; capacidade livre do volume contendo `CENTRAL_DATA_DIR` via `shutil.disk_usage`. Falhas retornam **indisponível**, jamais zero inventado.
- `GET /api/system/resources`: exige autenticação e cliente de loopback; consulta de leitura apenas, sem expor caminhos, processos, prompts nem credenciais.
- `frontend/src/ResourceMonitorPanel.jsx`: aparece em **Monitoramento**, atualiza a cada 15 segundos quando a página está visível e distingue medições físicas de reservas cooperativas.
- `central/main.py` injeta um mesmo `ResourceOrchestrator` na fila local de mídia.
- `central/motion_queue.py`: usa um slot de GPU **somente durante inicialização/execução Wan**. Aguarda por uma reserva local, acompanha cancelamento e atualiza o heartbeat durante a espera. Libera a reserva mesmo quando o backend falha. Outros motores e processos externos não são controlados.
- `tests/test_resource_telemetry.py` e `tests/test_resource_api.py`: testes determinísticos e de autenticação, sem GPU obrigatória.

**Atenção:** reservas continuam sendo apenas no processo Python da Central. Não impedem que Ollama, outra instância da Central, um ComfyUI externo ou o driver usem a GPU. `gpu_slots=1` não representa a disponibilidade física da VRAM. A fase 2 não mata nem descarrega processos e não promete aumento de throughput. Ela não bloqueia geração caso o NVIDIA-SMI esteja indisponível.

## Fase 3 — coordenação entre processos (experimental)

- `central/persistent_resources.py` cria uma base **SQLite WAL** separada na pasta de dados: `resource-leases.sqlite3`. Cada solicitação possui ticket de espera durável e uma concessão com token aleatório, número de geração monotônico (*fencing*), prazo de validade e renovação automática por heartbeat.
- O `BEGIN IMMEDIATE` do SQLite serializa as decisões de reserva entre **instâncias que compartilham exatamente a mesma pasta de dados**, tanto em Windows quanto Linux. Prioridade maior atende primeiro; empates obedecem ao ticket FIFO. Tickets abandonados expiram, concessões sem heartbeat deixam de bloquear a fila.
- Os orçamentos são declarativos: até um slot de GPU compartilhado por padrão, sem inventar VRAM disponível. RAM/VRAM/disco podem receber orçamentos administrados, mas **a configuração de orçamento automático não está ativa**.
- O `MotionQueue` obtém a concessão antes de iniciar o ComfyUI e confirma sua titularidade nos checkpoints Wan. Em perda de titularidade ou cancelamento, interrompe a tarefa sem encerrar outros processos. A renovação ocorre em thread dedicada enquanto a tarefa está ativa.
- `GET /api/system/resources` e o painel **Monitoramento** agora apresentam reservas de processos cooperantes da mesma pasta de dados, sem divulgar tokens, donos, modelos, prompts ou caminhos.
- `tests/test_persistent_resources.py`: verifica competição entre instâncias e entre processos reais, timeout, cancelamento, substituição de concessão vencida e heartbeat, sem executar modelos.

**Limitação crítica:** SQLite coordena apenas componentes integrados à Central. Ollama, um ComfyUI já aberto externamente, um processo que usa outra pasta de dados e o Qwen Image ainda não participam desses leases. Mesmo se uma requisição Ollama futura passar por um lease, o modelo pode permanecer na VRAM após a resposta — a residência deve ser tratada antes de prometer isolamento efetivo. Nenhum descarregamento de modelos é realizado automaticamente. Um processo congelado que continue gerando após perder o lease pode causar uso concorrente; por isso a verificação nos checkpoints é obrigatória, mas não equivale ao isolamento no driver NVIDIA.

## Fase 4 — residência do Ollama (somente observação)

- `central/ollama_residency.py`: consulta **somente por GET** o endpoint oficial `http://127.0.0.1:11434/api/ps`, sem enviar prompts nem comandos de `stop`, `load`, `generate` ou `keep_alive`. Não permite URL arbitrária, redirecionamentos ou proxies do ambiente. O corpo é limitado a 64 KiB, com timeout de conexão.
- Valida e resume o retorno em `loaded_count`, `models[].name`, `models[].vram_mib`, `reported_vram_mib` e `all_vram_sizes_known`. Se faltar `size_vram` ou o endpoint não responder, **não presume zero de VRAM**.
- `GET /api/system/resources` inclui o campo `ollama`. O painel **Monitoramento** identifica modelos ainda residentes depois da conclusão de chamadas e distingue a estimativa de VRAM do Ollama da VRAM total medida pelo NVIDIA-SMI. **Não somar os dois valores**: a VRAM Ollama já faz parte da medição global.
- Testes determinísticos em `tests/test_ollama_residency.py` para parsing, endpoint fixo, respostas malformadas, limite de tamanho, falha de conexão e ausência de uso de proxy.
- Fonte primária do contrato: [Ollama GET /api/ps](https://github.com/ollama/ollama/blob/main/docs/api.md).

**Importante:** Ollama atualmente permanece um serviço independente. Uma reserva adquirida por Wan **não obriga Ollama a liberar seus modelos residentes**. O novo módulo fornece diagnóstico, não exclusividade GPU nem descarregamento automático. Não foram alteradas configurações do Ollama e não é necessário instalar modelos adicionais.

## Limites explícitos

A fase 1 não estava ligada a motores. Na fase 3, a fila Wan reserva um slot compartilhado entre instâncias da Central que usam a mesma pasta de dados, mas **não há integração com o escalonamento do Ollama ou com a memória real alocada**. A Central agora mede a memória reportada pelo SO e pelo NVIDIA-SMI, mas não aloca memória, não move pesos, não faz streaming de parâmetros, não modifica a instalação e não controla processos externos. Reservas não equivalem a memória livre. Orçamentos `None` significam *desconhecidos*, não ilimitados. O lock e a fila agora são persistidos no SQLite local; serviços não participantes continuam fora da coordenação. Nenhuma rotina de eviction é automática.

## Exemplo do contrato

```python
from central.resource_orchestrator import ResourceLimits, ResourceOrchestrator, ResourceRequest

resources = ResourceOrchestrator(ResourceLimits(vram_mb=10000, gpu_slots=1))
with resources.reserve(ResourceRequest("motion_wan", vram_mb=8500, gpu_slots=1), timeout=30):
    # Um adaptador confiável executaria o motor aqui após validar permissões.
    pass
```

Valores exemplificativos, não medições da RTX 3060 12 GB.

## Próximas etapas, ainda não implementadas

1. Evoluir da observação para uma política de admissão explícita (com consentimento) que avalie modelos Ollama residentes e tarefas Wan antes de prometer exclusividade, sem interromper modelos de outras aplicações.
2. Integrar um motor de imagens com reservas cooperativas e configurar orçamentos conservadores com métricas físicas e autorização explícita para realocação; jamais assumir que uma leitura isolada garante capacidade.
3. Estender checkpoints do motor Wan para verificar titularidade mesmo em operações longas que não enviam atualizações frequentes.
4. Avaliar descarregamento opcional **somente após** confirmar ociosidade e permissão explícita do usuário.
5. Testar na RTX 3060 real (pico de memória, latência, throughput, falhas, cancelamento e recuperação).

## Validação

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ollama_residency.py tests/test_resource_orchestrator.py tests/test_persistent_resources.py tests/test_resource_telemetry.py tests/test_resource_api.py tests/test_motion_queue.py -q
```

A suíte adicionada foi projetada para rodar em CI sem GPU, verificando contratos, concorrência entre processos Python independentes e leituras simuladas. Não afirma ganho de desempenho nem homologação de execução com modelos reais. A UI exibe o diagnóstico efetivo somente quando a Central local está em execução.
