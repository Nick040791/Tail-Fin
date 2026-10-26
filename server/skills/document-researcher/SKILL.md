---
name: document-researcher
description: Searches and synthesizes documents across Google Drive, long-term PostgreSQL memory, and live web pages.
slash_command: /research
triggers: ["find in drive", "search drive", "my documents", "google doc", "spreadsheet", "research"]
required_tools: ["drive_search", "drive_read", "drive_list_folder", "drive_create_file", "web_search", "web_fetch", "memory_remember"]
---
# Document Researcher Workflow
1. Search the user's Google Drive using `drive_search` (filter by `doc`, `sheet`, `pdf`, or `any`).
2. Read matching documents in full using `drive_read(file_id=...)`.
3. Supplement internal documents with `web_search` and `web_fetch` when external context is requested.
4. Save newly synthesized notes to Google Drive (`drive_create_file`) or PostgreSQL memory (`memory_remember`) when requested.
