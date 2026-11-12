# AI Resource Orchestrator — fase 1

Inspiração técnica: [kimi-k3-in-c](https://github.com/FareedKhan-dev/kimi-k3-in-c), especialmente `docs/ARCHITECTURE.md` e `docs/TUNING.md`. Este módulo é implementação independente; não reproduz o motor de inferência K3 nem seus pesos.

## Implementado

- `central/resource_orchestrator.py`: gerenciador **cooperativo em um processo** de reservas declaradas de RAM, VRAM, armazenamento temporário e slots exclusivos de GPU, com prioridades 0–9, FIFO entre iguais, cancelamento, timeout e liberação idempotente.
- `plan_weight_placement`: recomendação matemática para manter pesos frequentes em GPU/RAM e marcar o restante como candidato a streaming **somente se o backend declarar compatibilidade**.
- `ResidentModelPlanner`: propostas LRU de liberação de modelos ociosos; nunca encerra processos ou descarrega pesos.
- `snapshot`: orçamento e uso declarado, sem expor prompts, caminhos ou credenciais.
- Testes unitários em `tests/test_resource_orchestrator.py`.

## Limites explícitos

A fase 1 **não está ligada à fila de inferência, ao Ollama ou ao ComfyUI/Wan**. Ela não mede uso real da GPU, não aloca memória, não move pesos, não faz streaming de parâmetros, não modifica a instalação e não controla processos externos. Reservas não equivalem a memória livre. Orçamentos `None` significam *desconhecidos*, não ilimitados. O lock e a fila são locais ao processo; serviços distintos requerem persistência e coordenação global. Nenhuma rotina de eviction é automática.

## Exemplo do contrato

```python
from central.resource_orchestrator import ResourceLimits, ResourceOrchestrator, ResourceRequest

resources = ResourceOrchestrator(ResourceLimits(vram_mb=10000, gpu_slots=1))
with resources.reserve(ResourceRequest("motion_wan", vram_mb=8500, gpu_slots=1), timeout=30):
    # Um adaptador confiável executaria o motor aqui após validar permissões.
    pass
```

Valores exemplificativos, não medições da RTX 3060 12 GB.

## Etapas seguintes, ainda não implementadas

1. Inventário de RAM, VRAM e SSD por sensores e APIs confiáveis, distinguindo capacidade livre física e reservas declaradas.
2. Leases interprocessos persistentes e recuperáveis com TTL, heartbeat, proprietário, cancelamento e prevenção de dupla reserva.
3. Adaptadores auditados para Ollama, ComfyUI/Wan e um motor de imagens, preservando permissões e APIs nativas; não matar processos de terceiros.
4. Descarregamento opcional após confirmar ociosidade e política de autorização.
5. Dashboard e testes reais na RTX 3060 (pico de memória, latência, throughput, falhas e recuperação).

## Validação

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_resource_orchestrator.py -q
```

Testes unitários aprovados apenas validam o contrato. Não afirmam execução ou ganho de desempenho com modelos reais.
