from __future__ import annotations

from textwrap import dedent


SUPPORTED_TOOLS = [
    {
        "name": "status",
        "summary": "Return workspace-level memory counts and graph stats.",
    },
    {
        "name": "recall",
        "summary": "Run the main Engram retrieval flow against the workspace.",
    },
    {
        "name": "recall_recent",
        "summary": "Load the most recent memories for the workspace.",
    },
    {
        "name": "remember",
        "summary": "Store a new memory in the workspace.",
    },
    {
        "name": "remember_decision",
        "summary": "Store an explicit decision and rationale.",
    },
    {
        "name": "remember_project",
        "summary": "Update project-level state for the workspace.",
    },
    {
        "name": "focus_brief",
        "summary": "Generate a brief about the most relevant memory context for a task.",
    },
    {
        "name": "hotspots",
        "summary": "Identify dense or high-interest areas in the memory graph.",
    },
    {
        "name": "compare_queries",
        "summary": "Compare how two queries retrieve and overlap.",
    },
]


STARTER_SKILLS = {
    "workspace-memory": {
        "name": "workspace-memory",
        "title": "Workspace Memory",
        "summary": "Use the hosted workspace memory service for project recall, remember, and recent context.",
        "body": dedent(
            """
            # Workspace Memory

            Use this service when the task needs durable project memory that survives across sessions.

            ## What to use it for

            - recall prior project context before doing substantial work
            - store decisions, blockers, and verified outcomes
            - query recent memory before picking work back up

            ## Preferred flow

            1. Call `status` to confirm the workspace is reachable.
            2. Call `recall` or `recall_recent` to load the most relevant context.
            3. Do the work.
            4. Call `remember`, `remember_decision`, or `remember_project` with the durable outcome.

            ## Notes

            - Keep stored memories short and specific.
            - Prefer facts and decisions over vague summaries.
            - Use `recall_recent` if you only need the last few entries.
            """
        ).strip(),
    },
    "session-handoff": {
        "name": "session-handoff",
        "title": "Session Handoff",
        "summary": "Capture the minimum high-value handoff state before stopping work.",
        "body": dedent(
            """
            # Session Handoff

            Before you stop, make sure the next session can pick the work up cleanly.

            ## Save these

            - current state
            - key decision
            - main unresolved issue
            - file path or repo name if relevant

            ## Good pattern

            - `recall` on startup
            - `remember` during meaningful progress
            - `remember_decision` for tradeoffs
            - `remember_project` when project status changes
            """
        ).strip(),
    },
}


def starter_skill_list() -> list[dict]:
    return [
        {"name": skill["name"], "title": skill["title"], "summary": skill["summary"]}
        for skill in STARTER_SKILLS.values()
    ]


def render_skill_markdown(skill_name: str) -> str | None:
    skill = STARTER_SKILLS.get(skill_name)
    if not skill:
        return None
    return f"{skill['body']}\n"
