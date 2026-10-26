---
name: schedule-coordinator
description: Manages Google Calendar appointments, checks availability, detects scheduling conflicts, and coordinates meeting invitations.
slash_command: /schedule
triggers: ["schedule", "calendar", "free time", "availability", "book a meeting", "appointment"]
required_tools: ["calendar_list", "calendar_create", "calendar_delete", "gmail_prepare_send", "contacts_search"]
---
# Schedule Coordinator Workflow
1. Always call `calendar_list` first to check existing events and avoid double-booking before creating an event.
2. Use ISO-8601 timestamps with the local timezone offset when calling `calendar_create`.
3. If deleting or cancelling an existing event, use `calendar_delete` (which stages an approval confirmation).
4. If sending meeting times to a contact, look up their email with `contacts_search` and stage the email with `gmail_prepare_send`.
