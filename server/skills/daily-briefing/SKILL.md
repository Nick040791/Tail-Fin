---
name: daily-briefing
description: Generates a concise executive briefing combining Calendar schedule, unread Gmail messages, recent phone SMS texts, and open tasks.
slash_command: /briefing
triggers: ["briefing", "morning update", "catch me up", "what's on my plate", "daily summary", "what do i have today"]
required_tools: ["calendar_list", "gmail_search", "messages_recent", "task_list"]
---
# Daily Briefing Workflow
When generating a daily briefing for the user:
1. Call `calendar_list(days=2)` to check today's and tomorrow's schedule.
2. Call `gmail_search(query="is:unread newer_than:2d", max_results=10)` to inspect recent unread emails.
3. Call `messages_recent(limit=10)` to check the latest phone SMS texts.
4. Call `task_list(status="open")` to check open tasks, reminders, and job applications.
5. Present a structured, easy-to-scan briefing:
   - **📅 Schedule**: Today's events and upcoming conflicts.
   - **📧 Priority Emails**: Important unread emails (ignore obvious marketing noise).
   - **📱 Phone Texts**: Recent SMS messages requiring attention.
   - **✅ Open Tasks & Follow-ups**: Top pending tasks.
