---
name: inbox-triage
description: Triages unread Gmail messages and recent phone SMS texts into prioritized categories and offers to draft replies with approval.
slash_command: /triage
triggers: ["triage", "check my inbox", "unread emails", "check my messages", "reply to emails"]
required_tools: ["gmail_search", "gmail_read", "gmail_prepare_send", "messages_recent", "messages_thread"]
---
# Inbox Triage Workflow
1. Search unread emails via `gmail_search(query="is:unread newer_than:3d", max_results=12)` and check recent texts via `messages_recent(limit=12)`.
2. For any email from a real person, recruiter, employer, or service requiring action, call `gmail_read` on its `message_id` to get the full context.
3. Categorize items into:
   - 🚨 **Urgent / Action Required**
   - 💼 **Job Search & Interviews**
   - 💬 **Personal Texts & Threads**
   - 📌 **Low Priority / FYI**
4. When the user wants to reply to an email, always use `gmail_prepare_send` so it is staged for user approval before sending.
