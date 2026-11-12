# AI Resource Orchestrator — fases 1 e 2

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

## Limites explícitos

A fase 1 não estava ligada a motores. Na fase 2, a fila Wan reserva um slot cooperativo dentro do mesmo processo, mas **não há integração com o escalonamento do Ollama ou com a memória real alocada**. A Central agora mede a memória reportada pelo SO e pelo NVIDIA-SMI, mas não aloca memória, não move pesos, não faz streaming de parâmetros, não modifica a instalação e não controla processos externos. Reservas não equivalem a memória livre. Orçamentos `None` significam *desconhecidos*, não ilimitados. O lock e a fila são locais ao processo; serviços distintos requerem persistência e coordenação global. Nenhuma rotina de eviction é automática.

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

1. Leases interprocessos persistentes e recuperáveis com TTL, heartbeat, proprietário, cancelamento e prevenção de dupla reserva.
2. Adaptadores auditados para Ollama e um motor de imagens, preservando permissões e APIs nativas; não matar processos de terceiros.
3. Configuração conservadora de orçamentos de RAM/VRAM a partir de métricas coletadas; nunca assumir que uma leitura isolada garante capacidade.
4. Descarregamento opcional após confirmar ociosidade e política de autorização.
5. Testes reais na RTX 3060 (pico de memória, latência, throughput, falhas, cancelamento e recuperação).

## Validação

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_resource_orchestrator.py -q
```

A suíte adicionada foi projetada para rodar em CI sem GPU, verificando contratos e leituras simuladas. Não afirma ganho de desempenho nem homologação de execução com modelos reais. A UI exibe o diagnóstico efetivo somente quando a Central local está em execução.
