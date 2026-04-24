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
        "name": "access_patterns",
        "summary": "Show which memories and entities are recalled most often.",
        "args": {"limit": "integer, optional"},
    },
    {
        "name": "reranker_status",
        "summary": "Report whether the deep retrieval reranker is trained and available.",
        "args": {},
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
        "name": "recall_by_type",
        "summary": "Retrieve memories filtered by fact, procedure, or narrative type.",
        "args": {"memory_type": "fact | procedure | narrative", "limit": "integer, optional"},
    },
    {
        "name": "recall_layer",
        "summary": "Retrieve memories from one memory layer.",
        "args": {"layer": "working | episodic | semantic | procedural", "limit": "integer, optional"},
    },
    {
        "name": "recall_timeline",
        "summary": "Retrieve memories from a date range.",
        "args": {"start": "YYYY-MM or YYYY-MM-DD", "end": "YYYY-MM or YYYY-MM-DD, optional"},
    },
    {
        "name": "recall_related",
        "summary": "Traverse related memory context from an entity.",
        "args": {"name": "string", "max_hops": "integer, optional"},
    },
    {
        "name": "recall_explain",
        "summary": "Return retrieval results with scoring and query expansion details.",
        "args": {"query": "string", "top_k": "integer, optional", "mode": "facts_only | facts_plus_rules | full_context, optional"},
    },
    {
        "name": "search_entities",
        "summary": "Fuzzy-search entity names for lookup and disambiguation.",
        "args": {"query": "string", "limit": "integer, optional"},
    },
    {
        "name": "entity_graph",
        "summary": "Return a JSON subgraph for a named entity.",
        "args": {"name": "string"},
    },
    {
        "name": "entity_timeline",
        "summary": "Return one entity's memories ordered by date.",
        "args": {"name": "string"},
    },
    {
        "name": "backlinks",
        "summary": "Find memories that reference or link to a memory.",
        "args": {"memory_id": "string"},
    },
    {
        "name": "find_similar",
        "summary": "Find memories semantically similar to a memory.",
        "args": {"memory_id": "string", "top_k": "integer, optional"},
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
        "name": "diary_read",
        "summary": "Read the current session diary.",
        "args": {},
    },
    {
        "name": "diary_write",
        "summary": "Append a concise entry to the current session diary.",
        "args": {"entry": "string"},
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
        "name": "compress",
        "summary": "Return a compressed summary of retrieved memories for a query.",
        "args": {"query": "string", "max_tokens": "integer, optional"},
    },
    {
        "name": "annotate",
        "summary": "Attach an operator note to a memory without changing its content.",
        "args": {"memory_id": "string", "note": "string"},
    },
    {
        "name": "edit_memory",
        "summary": "Edit a memory's content and re-embed it.",
        "args": {"memory_id": "string", "new_content": "string"},
    },
    {
        "name": "invalidate",
        "summary": "Mark a memory as no longer true.",
        "args": {"memory_id": "string", "reason": "string, optional"},
    },
    {
        "name": "update_status",
        "summary": "Move a memory through active, challenged, invalidated, merged, or superseded states.",
        "args": {"memory_id": "string", "new_status": "active | challenged | invalidated | merged | superseded", "reason": "string, optional"},
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
    {
        "name": "promote",
        "summary": "Promote a memory to a higher layer.",
        "args": {"memory_id": "string", "target_layer": "working | episodic | semantic | procedural"},
    },
    {
        "name": "demote",
        "summary": "Demote a memory to a lower layer.",
        "args": {"memory_id": "string", "target_layer": "working | episodic | semantic | procedural"},
    },
    {
        "name": "unpin",
        "summary": "Remove a pin from a memory.",
        "args": {"memory_id": "string"},
    },
    {
        "name": "link_memories",
        "summary": "Manually link two memories through their entities.",
        "args": {"memory_id_1": "string", "memory_id_2": "string", "relation": "string, optional"},
    },
    {
        "name": "update_entity",
        "summary": "Add an alias or metadata to an entity.",
        "args": {"name": "string", "alias": "string, optional", "metadata": "object, optional"},
    },
    {
        "name": "merge_entities",
        "summary": "Merge one entity into another.",
        "args": {"source_name": "string", "target_name": "string"},
    },
    {
        "name": "batch_tag",
        "summary": "Add tags to memories matching a search query.",
        "args": {"query": "string", "tags": "array", "top_k": "integer, optional"},
    },
    {
        "name": "dedup",
        "summary": "Find and merge near-duplicate memories by similarity.",
        "args": {"threshold": "number, optional", "max_merges": "integer, optional"},
    },
    {
        "name": "detect_communities",
        "summary": "Detect entity communities and optionally generate summaries.",
        "args": {"min_size": "integer, optional", "generate_summaries": "boolean, optional"},
    },
    {
        "name": "consolidate",
        "summary": "Run a dream cycle to cluster, summarize, and generate peer cards.",
        "args": {},
    },
    {
        "name": "extract_patterns",
        "summary": "Extract reusable procedural patterns from recent activity.",
        "args": {"hours": "integer, optional", "dry_run": "boolean, optional", "novelty_threshold": "number, optional"},
    },
    {
        "name": "session_summary",
        "summary": "Summarize the current session from diary and recent events.",
        "args": {},
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
