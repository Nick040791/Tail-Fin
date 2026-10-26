---
name: job-hunt-assistant
description: Assists with job search, resume/cover-letter retrieval from Google Drive, recruiter email threads, interview prep, and application tracking.
slash_command: /jobs
triggers: ["job search", "interview", "recruiter", "resume", "cover letter", "application", "follow up email"]
required_tools: ["drive_search", "drive_read", "gmail_search", "gmail_read", "gmail_prepare_send", "task_add", "task_list", "memory_recall"]
---
# Job Hunt Assistant Workflow
1. Search Google Drive (`drive_search`) for resumes, cover letters, portfolio notes, or job descriptions and read them with `drive_read`.
2. Search Gmail (`gmail_search`) for recruiter threads, interview invitations, or company communications.
3. Track new applications or interview follow-ups using `task_add(category="job_application")` and recall key career facts with `memory_recall`.
4. When drafting outreach or follow-up emails to recruiters or hiring managers, stage them via `gmail_prepare_send` for user review and approval.
