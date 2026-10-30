"""Independent full-stack acceptance gate: audited Central run plus live UI/API evidence.

The companion operator CLI must collect the HTTP/browser report itself. Never
treat a model's written summary as proof of a working application.
"""
from pathlib import Path
from .agent_registry import effective_specialty
from .task_contract import delivery_evidence

ROLES = ("architecture", "frontend", "backend", "review")
DEVTOOLS = ("take_snapshot", "fill", "click", "list_console_messages",
            "lighthouse_audit:desktop", "lighthouse_audit:mobile")
API = ("health", "anonymous_denied", "register", "login", "team_create",
       "task_create", "task_update", "task_list_persisted", "task_filter")
BROWSER = ("login", "task_visible", "task_created", "no_console_errors",
           "no_request_errors", "no_overflow")


class AcceptanceError(ValueError):
    """The caller has not identified a permitted run and workspace."""


def evaluate(db, user_id, run_id, workspace, independent):
    run = db.one("SELECT id,user_id,status FROM runs WHERE id=? AND user_id=?",
                 (run_id, user_id))
    binding = db.one("SELECT folder FROM run_workspace_bindings WHERE run_id=? AND user_id=?",
                     (run_id, user_id))
    if not run or not binding:
        raise AcceptanceError("Execucao ou vinculo nao autorizado.")
    root = Path(workspace).resolve(strict=True)
    if (not root.is_dir() or root != Path(binding["folder"]).resolve(strict=True)):
        raise AcceptanceError("Workspace difere do original da execucao.")

    checks = {}
    def check(key, passed, detail):
        checks[key] = {"passed": bool(passed), "detail": detail}

    check("completed", run["status"] == "completed", "Run precisa concluir.")
    steps = db.all(
        "SELECT s.kind,s.status,a.id AS owner_agent,a.specialty,a.name,a.instructions "
        "FROM steps s LEFT JOIN agents a ON a.id=s.agent_id AND a.user_id=? "
        "WHERE s.run_id=?", (user_id, run_id))
    roles = {effective_specialty(row) for row in steps if
             row["kind"] == "agent" and row["status"] == "completed" and row["owner_agent"]}
    check("team", set(ROLES).issubset(roles), "Arquiteto, frontend, backend e revisor.")
    delegated = db.one("SELECT COUNT(*) AS n FROM dynamic_step_requests WHERE run_id=?", (run_id,))
    check("delegation", bool(delegated and delegated["n"]), "Subtarefa persistida no DAG.")
    iso = db.one("SELECT enabled FROM isolated_workspace_runs WHERE run_id=? AND user_id=?",
                 (run_id, user_id))
    sessions = db.all("SELECT state FROM isolated_workspace_steps WHERE run_id=? AND user_id=?",
                      (run_id, user_id))
    states = [row["state"] for row in sessions]
    check("worktree_promotion", bool(iso and iso["enabled"] and states
          and all(state in ("approved", "unchanged") for state in states)
          and "approved" in states), "Worktree integrado por aprovacao do operador.")
    proof = delivery_evidence(db, run_id)
    files = proof["changed_files"]
    check("sources", any(f.startswith("frontend/") for f in files) and
          any(f.startswith("backend/") for f in files),
          "Arquivos frontend e backend modificados por ferramentas.")
    check("post_edit_tests", proof["tests_passed"] and proof["validation_after_last_change"],
          "Testes depois da ultima promocao.")
    qa = set(proof["verified_browser_checks_after_last_change"])
    check("devtools", set(DEVTOOLS).issubset(qa),
          "Snapshot, fill, click, console e Lighthouse desktop/mobile aprovados.")
    for name in ("frontend/package.json", "frontend/src/App.tsx", "backend/main.py"):
        file = root / name
        check("artifact_" + name, file.is_file() and not file.is_symlink()
              and file.resolve().is_relative_to(root), "Arquivo real: " + name)
    if not isinstance(independent, dict):
        independent = {}
    api = independent.get("api")
    api = api if isinstance(api, dict) else {}
    for name in API:
        check("api_" + name, api.get(name) is True, "HTTP independente: " + name)
    devices = independent.get("devices")
    devices = devices if isinstance(devices, dict) else {}
    for device in ("desktop", "mobile"):
        actual = devices.get(device)
        actual = actual if isinstance(actual, dict) else {}
        for criterion in BROWSER:
            check("ui_" + device + "_" + criterion, actual.get(criterion) is True,
                  "Playwright " + device + ": " + criterion)
    return {"schema_version": 1, "run_id": run_id,
            "passed": all(c["passed"] for c in checks.values()),
            "checks": checks,
            "failed": [k for k, c in checks.items() if not c["passed"]],
            "limitations": "Nao prova reinicio, sandbox de SO ou runtimes externos."}
