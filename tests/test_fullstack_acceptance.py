"""Regression tests for evidence-based full-stack acceptance."""
import pytest

from central.database import Database, utcnow
from central.fullstack_acceptance import (
    AcceptanceError, API, BROWSER, evaluate
)


def fixture(tmp_path):
    root = tmp_path / "workspace"
    (root / "frontend/src").mkdir(parents=True)
    (root / "backend").mkdir()
    for name in ("frontend/package.json", "frontend/src/App.tsx", "backend/main.py"):
        (root / name).write_text("demo", encoding="utf-8")
    db = Database(tmp_path / "db.sqlite3")
    now = utcnow()
    db.execute("INSERT INTO users VALUES(?,?,?,?)", ("owner", "owner@example.invalid", "hash", now))
    db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?)",
               ("chat", "owner", "Test", None, now, now))
    db.execute(
        "INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,"
        "created_at,updated_at,autonomous) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("run", "owner", "chat", "Crie sistema", "completed", "team", "[]", "[]",
         now, now, 1))
    db.execute(
        "INSERT INTO run_workspace_bindings(run_id,user_id,folder,initial_mode,"
        "command_runner,created_at) VALUES(?,?,?,?,?,?)",
        ("run", "owner", str(root), "full", "host", now))
    for role in ("architecture", "frontend", "backend", "review"):
        db.execute("INSERT INTO agents(id,user_id,name,specialty,instructions,created_at)"
                   " VALUES(?,?,?,?,?,?)", (role, "owner", role, role, "", now))
        db.execute("INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,"
                   "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (role, "run", role, "agent", role, "[]", "completed", now, now))
    db.execute(
        "INSERT INTO dynamic_step_requests(step_id,run_id,requester_step_id,"
        "request_id,request_hash,depth,created_at) VALUES(?,?,?,?,?,?,?)",
        ("backend", "run", "frontend", "test-request", "hash", 1, now))
    db.execute(
        "INSERT INTO isolated_workspace_runs(run_id,user_id,root,enabled,head,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        ("run", "owner", str(root), 1, "abcdef", now, now))
    db.execute(
        "INSERT INTO isolated_workspace_steps(run_id,step_id,user_id,folder,head,"
        "state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        ("run", "frontend", "owner", str(root), "abcdef", "approved", now, now))
    for path in ("frontend/src/App.tsx", "backend/main.py"):
        db.event("run", "workspace_action_result", {
            "success": True, "summary": {"action": "write", "path": path}})
    db.event("run", "workspace_validation", {"passed": True, "results": []})
    for tool in ("take_snapshot", "fill", "click", "list_console_messages"):
        db.event("run", "workspace_action_result", {
            "success": True, "qa_pass": True,
            "summary": {"action": "browser_tool", "tool": tool}})
    for device in ("desktop", "mobile"):
        db.event("run", "workspace_action_result", {
            "success": True, "qa_pass": True,
            "summary": {"action": "browser_tool", "tool": "lighthouse_audit"},
            "browser_arguments": {"device": device}})
    return db, root


def independent():
    return {"api": {key: True for key in API},
            "devices": {device: {key: True for key in BROWSER}
                        for device in ("desktop", "mobile")}}


def test_complete_real_evidence_passes(tmp_path):
    db, root = fixture(tmp_path)
    try:
        report = evaluate(db, "owner", "run", root, independent())
        assert report["passed"] and not report["failed"]
    finally:
        db.close()


def test_model_summary_cannot_replace_independent_browser_and_api(tmp_path):
    db, root = fixture(tmp_path)
    try:
        report = evaluate(db, "owner", "run", root, {"api": {"health": True}})
        assert not report["passed"]
        assert "api_login" in report["failed"]
        assert "ui_mobile_login" in report["failed"]
    finally:
        db.close()


def test_last_failed_browser_check_blocks_stale_green(tmp_path):
    db, root = fixture(tmp_path)
    try:
        db.event("run", "workspace_action_result", {
            "success": False, "qa_issue": "Falha no clique",
            "summary": {"action": "browser_tool", "tool": "click"}})
        report = evaluate(db, "owner", "run", root, independent())
        assert not report["passed"] and "devtools" in report["failed"]
    finally:
        db.close()


def test_unapproved_promotion_and_old_validation_fail_closed(tmp_path):
    db, root = fixture(tmp_path)
    try:
        db.execute("UPDATE isolated_workspace_steps SET state='reviewed'")
        db.event("run", "workspace_validation", {"passed": False, "results": []})
        report = evaluate(db, "owner", "run", root, independent())
        assert "worktree_promotion" in report["failed"]
        assert "post_edit_tests" in report["failed"]
    finally:
        db.close()


def test_foreign_run_and_wrong_folder_are_rejected(tmp_path):
    db, root = fixture(tmp_path)
    try:
        with pytest.raises(AcceptanceError):
            evaluate(db, "other", "run", root, independent())
        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(AcceptanceError):
            evaluate(db, "owner", "run", other, independent())
    finally:
        db.close()


@pytest.mark.parametrize("address", [
    "https://127.0.0.1:8000/", "http://remote.example:8000/",
    "http://127.0.0.1:8000/secret", "http://127.0.0.1:8000/?foo=1",
    "http://test:secret@localhost:8000/", "file:///etc/passwd",
    "http://localhost/", "http://127.0.0.2:8000"
])
def test_independent_verifier_rejects_non_loopback_targets(address):
    from examples.verify_fullstack_acceptance import local_url
    with pytest.raises(AcceptanceError):
        local_url(address)


def test_independent_verifier_accepts_loopback_targets():
    from examples.verify_fullstack_acceptance import local_url
    assert local_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/"
    assert local_url("http://[::1]:8000/") == "http://[::1]:8000/"


def test_read_only_evidence_database_cannot_write(tmp_path):
    import sqlite3
    from examples.verify_fullstack_acceptance import ReadOnlyDatabase
    db, root = fixture(tmp_path)
    path = tmp_path / "db.sqlite3"
    db.close()
    reader = ReadOnlyDatabase(path)
    try:
        assert reader.one("SELECT id FROM runs WHERE id='run'")["id"] == "run"
        with pytest.raises(sqlite3.OperationalError):
            reader.conn.execute("DELETE FROM runs")
    finally:
        reader.close()
