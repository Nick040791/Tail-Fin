---
name: memory-curator
description: Stores, organizes, and recalls persistent user facts, preferences, contacts, and project history in PostgreSQL + pgvector.
slash_command: /memory
triggers: ["remember that", "save to memory", "what do you remember", "my preferences", "forget that"]
required_tools: ["memory_remember", "memory_recall", "memory_forget", "contacts_search"]
---
# Memory Curator Workflow
1. When the user shares durable personal preferences, contact details, career goals, or project facts, call `memory_remember` with an appropriate `category` (`preference`, `contact`, `project`, `job_search`, `fact`) and `importance` (1–5).
2. When answering questions that depend on prior context or personal details, call `memory_recall` to run a hybrid vector + full-text search over PostgreSQL.
3. If the user asks to remove outdated information, call `memory_forget`.
