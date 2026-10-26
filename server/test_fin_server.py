#!/usr/bin/env python3
"""Automated unit & integration test suite for the Fin Agent Server."""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config
import db
import mcp_bridge
import plugins
import server as srv
import skills
import tools


class FinAssistantUpgradeTests(unittest.TestCase):
    def test_01_default_model_and_provider(self):
        model = config.get_default_model()
        self.assertEqual(model, "Fin:latest")
        provider, clean, _, _ = config.resolve_provider(model)
        self.assertEqual(provider, "ollama")
        self.assertEqual(clean, "Fin:latest")

    def test_02_database_and_pgvector_memory(self):
        self.assertTrue(db.db_available(), "PostgreSQL fin-postgres container should be reachable")
        self.assertTrue(db.init_db_schema())

        saved = tools.tool_memory_remember({
            "content": "Fin Assistant uses PostgreSQL 17 with pgvector for hybrid memory.",
            "category": "project",
            "subject": "Architecture",
            "importance": 4,
        })
        self.assertIn("Saved to long-term memory", saved)

        recalled = tools.tool_memory_recall({"query": "What database does Fin use for hybrid memory?"})
        self.assertIn("pgvector", recalled)

    def test_03_phone_messages_tools(self):
        recent = tools.tool_messages_recent({"limit": 5})
        self.assertIn("recent phone message", recent)

        searched = tools.tool_messages_search({"query": "pickup"})
        self.assertIn("323297170-K", searched)

        thread = tools.tool_messages_thread({"address_or_name": "6315025850"})
        self.assertIn("323297170-K", thread)

    def test_04_gmail_and_drive_approval_gates_with_natural_language(self):
        # Stage a Gmail send via gmail_prepare_send
        staged = tools.tool_gmail_prepare_send({
            "to": "hiring@example.com",
            "subject": "Application Follow-up",
            "body": "Hello, checking in on my application.",
        })
        self.assertIn("EMAIL READY FOR APPROVAL", staged)

        # Verify /pending shows it
        pending = srv.handle_slash_command("/pending")
        self.assertIn("hiring@example.com", pending)

        # Cancel it using natural language ("no, cancel it")
        nl_reply = plugins.check_natural_language_approval("no, cancel it")
        self.assertIsNotNone(nl_reply)
        self.assertIn("Cancelled pending action", nl_reply)

        # Stage a Google Drive file update and cancel via natural language
        drive_staged = tools.tool_drive_update_file({
            "file_id": "test_doc_123",
            "new_content": "Updated resume text",
        })
        self.assertIn("PENDING DRIVE UPDATE APPROVAL", drive_staged)
        nl_cancel_drive = plugins.check_natural_language_approval("cancel that")
        self.assertIn("Cancelled pending action", nl_cancel_drive)

    def test_05_skills_engine(self):
        all_skills = skills.load_all_skills()
        self.assertEqual(len(all_skills), 6)
        matched = skills.match_skills_for_prompt("Please triage my unread emails and check my inbox")
        self.assertTrue(any(s["name"] == "inbox-triage" for s in matched))

    def test_06_mcp_client_and_server_bridge(self):
        defs, routes = mcp_bridge.discover_mcp_tools(force_reload=True)
        mcp_names = [d["function"]["name"] for d in defs]
        self.assertIn("mcp__fin_workspace__system_status", mcp_names)

        # Execute read-only MCP tool
        status_out = mcp_bridge.call_mcp_tool("mcp__fin_workspace__system_status", {})
        self.assertIn("Load Average:", status_out)

        # Execute approval-gated MCP tool (workspace_write_file)
        write_out = mcp_bridge.call_mcp_tool(
            "mcp__fin_workspace__workspace_write_file",
            {"filename": "test_note.md", "content": "Hello from MCP"},
        )
        self.assertIn("PENDING MCP TOOL APPROVAL", write_out)
        # Cancel the staged MCP approval
        plugins.check_natural_language_approval("reject")

        # Verify fin_mcp_server.py over stdio JSON-RPC
        proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "mcp_bridge", "fin_mcp_server.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        out, _ = proc.communicate("\n".join(json.dumps(r) for r in reqs) + "\n", timeout=10)
        lines = [json.loads(line) for line in out.strip().splitlines()]
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "fin-assistant-mcp")
        self.assertGreaterEqual(len(lines[1]["result"]["tools"]), 25)


if __name__ == "__main__":
    unittest.main()
