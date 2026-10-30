"""Legacy shared-workspace jobs must not require an unrelated agent identity.

When isolation is enabled, identity, Git root and run-bound workspace remain
mandatory. This test exercises disabled behavior only.
"""
from central.database import Database, utcnow
from central.computer_access import set_policy
from central.isolated_workspaces import execution_folder, prepare_step, finish_step, checkpoint_folder


def test_shared_legacy_worker_keeps_original_folder_without_isolation(tmp_path):
    db = Database(tmp_path / "shared.sqlite3")
    try:
        now = utcnow()
        db.execute("INSERT INTO users VALUES(?,?,?,?)", ("u", "u@example.invalid", "h", now))
        db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?)",
                   ("c", "u", "Test", None, now, now))
        db.execute("INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("r", "u", "c", "Task", "running", "manual", "[]", "[]", now, now))
        db.execute("INSERT INTO steps(id,run_id,kind,name,deps,status,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   ("s", "r", "agent", "Old", "[]", "running", now, now))
        set_policy(db, "u", "full", str(tmp_path))
        assert prepare_step(db, "u", "r", "s") == str(tmp_path.resolve())
        assert execution_folder(db, "u", "r", "s") == str(tmp_path.resolve())
        assert checkpoint_folder(db, "u", "r", "s") == str(tmp_path.resolve())
        assert finish_step(db, "u", "r", "s")['status'] == "shared"
    finally:
        db.close()
