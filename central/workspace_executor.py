"""Injectable execution service. Authorization stays ahead of every runner.

Runners are server-side dependencies, never instances supplied in model JSON.
The default runner retains Docker selection, limits, cancellation and scoping.
"""
from .approval_engine import ApprovalEngine


class WorkspaceExecutor:
    def __init__(self, db, approvals=None, runner=None):
        self.db = db
        self.approvals = approvals if approvals is not None else ApprovalEngine(db)
        self.runner = runner

    def execute(self, folder, request, run_id=None):
        from .workspace_tools import execute
        runner = self.runner if self.runner is not None else execute
        return runner(folder, request, run_id)

    async def action(self, db, user_id, run_id, step_id, request, emit):
        if db is not self.db:
            raise ValueError('Workspace executor belongs to another database')
        from .workspace_tools import agent_action
        return await agent_action(db, user_id, run_id, step_id, request, emit, executor=self)
