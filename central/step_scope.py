"""Resolve execution paths from server-held run/step bindings, never model paths."""
from .workspace_guard import enforce_run_scope


def execution_folder(db, user_id, run_id, step_id, *, write=False):
    original = enforce_run_scope(db, user_id, run_id, write=write)
    from .isolated_workspaces import execution_folder as isolated_folder
    return isolated_folder(db, user_id, run_id, step_id) or original
