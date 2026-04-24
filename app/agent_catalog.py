from __future__ import annotations

from textwrap import dedent


SUPPORTED_TOOLS = [
    {
        "name": "status",
        "summary": "Return workspace-level memory counts and graph stats.",
        "args": {},
    },
    {
        "name": "health",
        "summary": "Check memory indexes, cache state, and workspace runtime health.",
        "args": {},
    },
    {
        "name": "memory_map",
        "summary": "Build a high-level map of layers, entities, and recent memory activity.",
        "args": {},
    },
    {
        "name": "quality_metrics",
        "summary": "Return storage quality, curation, and retrieval quality metrics.",
        "args": {},
    },
    {
        "name": "count_by",
        "summary": "Count memories by layer, source type, entity, or month.",
        "args": {"group_by": "layer | source_type | entity | month"},
    },
    {
        "name": "recall",
        "summary": "Run the main Engram retrieval flow against the workspace.",
        "args": {"query": "string", "top_k": "integer, optional", "mode": "facts_only | facts_plus_rules | full_context, optional"},
    },
    {
        "name": "recall_context",
        "summary": "Return a compact context block for prompt injection.",
        "args": {"query": "string", "max_tokens": "integer, optional"},
    },
    {
        "name": "recall_hints",
        "summary": "Return short memory hints that trigger recognition without flooding context.",
        "args": {"query": "string", "top_k": "integer, optional", "hint_length": "integer, optional"},
    },
    {
        "name": "recall_recent",
        "summary": "Load the most recent memories for the workspace.",
        "args": {"limit": "integer, optional"},
    },
    {
        "name": "recall_entity",
        "summary": "Return facts, relationships, and timeline for a named entity.",
        "args": {"name": "string"},
    },
    {
        "name": "search_entities",
        "summary": "Fuzzy-search entity names for lookup and disambiguation.",
        "args": {"query": "string", "limit": "integer, optional"},
    },
    {
        "name": "focus_brief",
        "summary": "Generate a brief about the most relevant memory context for a task.",
        "args": {"query": "string", "top_k": "integer, optional"},
    },
    {
        "name": "layers",
        "summary": "Return L0-L3 graduated context for system prompt injection.",
        "args": {"query": "string, optional", "max_tokens": "integer, optional"},
    },
    {
        "name": "get_skills",
        "summary": "Select the most relevant procedural skills for a task.",
        "args": {"query": "string", "max_skills": "integer, optional", "format": "boolean, optional"},
    },
    {
        "name": "remember",
        "summary": "Store a new memory in the workspace.",
        "args": {"content": "string", "layer": "string, optional", "memory_type": "fact | procedure | narrative, optional"},
    },
    {
        "name": "remember_decision",
        "summary": "Store an explicit decision and rationale.",
        "args": {"decision": "string", "rationale": "string, optional", "importance": "number, optional"},
    },
    {
        "name": "remember_error",
        "summary": "Store an error pattern with prevention guidance.",
        "args": {"error": "string", "prevention": "string, optional", "importance": "number, optional"},
    },
    {
        "name": "remember_interaction",
        "summary": "Store a durable question-and-answer exchange.",
        "args": {"question": "string", "answer": "string", "importance": "number, optional"},
    },
    {
        "name": "remember_negative",
        "summary": "Store explicit negative knowledge about what does not exist or should not be done.",
        "args": {"content": "string", "scope": "string, optional", "context": "string, optional", "importance": "number, optional"},
    },
    {
        "name": "remember_project",
        "summary": "Update project-level state for the workspace.",
        "args": {"name": "string", "status": "string, optional", "location": "string, optional", "notes": "string, optional"},
    },
    {
        "name": "session_checkpoint",
        "summary": "Persist a checkpoint note plus recent state for resumable agent sessions.",
        "args": {"note": "string, optional", "limit": "integer, optional"},
    },
    {
        "name": "session_handoff",
        "summary": "Build or save a structured handoff snapshot for another agent/session.",
        "args": {"save": "boolean, optional", "limit": "integer, optional", "session_id": "string, optional"},
    },
    {
        "name": "resume_context",
        "summary": "Load the latest handoff snapshot and related recent activity.",
        "args": {"session_id": "string, optional", "limit": "integer, optional"},
    },
    {
        "name": "hotspots",
        "summary": "Identify dense or high-interest areas in the memory graph.",
        "args": {"hours": "integer, optional", "limit": "integer, optional"},
    },
    {
        "name": "compare_queries",
        "summary": "Compare how two queries retrieve and overlap.",
        "args": {"query_a": "string", "query_b": "string", "top_k": "integer, optional"},
    },
    {
        "name": "export",
        "summary": "Export workspace memories as markdown or JSON.",
        "args": {"format": "markdown | json, optional", "layer": "string, optional", "limit": "integer, optional"},
    },
    {
        "name": "status_history",
        "summary": "Return lifecycle history for a memory.",
        "args": {"memory_id": "string"},
    },
    {
        "name": "tag",
        "summary": "Add or remove tags on a memory.",
        "args": {"memory_id": "string", "add": "array, optional", "remove": "array, optional"},
    },
    {
        "name": "pin",
        "summary": "Pin a memory so retention jobs keep it.",
        "args": {"memory_id": "string"},
    },
    {
        "name": "forget",
        "summary": "Soft-delete a memory from the workspace.",
        "args": {"memory_id": "string"},
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
            2. Call `recall_context`, `recall_hints`, `focus_brief`, or `recall_recent` to load the right amount of context.
            3. Do the work.
            4. Call `remember`, `remember_decision`, `remember_error`, `remember_negative`, or `remember_project` with the durable outcome.
            5. Call `session_checkpoint` or `session_handoff` when the work should be resumable.

            ## Notes

            - Keep stored memories short and specific.
            - Prefer facts and decisions over vague summaries.
            - Use `recall_recent` if you only need the last few entries.
            - Use `get_skills` before specialized work so the agent can inject only the relevant procedures.
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
