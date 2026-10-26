#!/usr/bin/env python3
"""One-time Google sign-in for the Fin server.

Run once on the PC after putting credentials.json (OAuth desktop-app
client, downloaded from Google Cloud Console) in this folder:

    pip install -r requirements-google.txt
    python auth_google.py

A browser window opens for the Google sign-in. The resulting token is
saved to token.json next to this file. Restart server.py afterwards —
Gmail and Calendar tools activate automatically when token.json exists.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "google-auth-oauthlib is not installed.\n"
            "Run: pip install -r requirements-google.txt"
        )
        sys.exit(1)

    creds_path = os.path.join(HERE, "credentials.json")
    if not os.path.exists(creds_path):
        print(
            "credentials.json not found in this folder.\n"
            "Create an OAuth client ID (Desktop app) in Google Cloud Console\n"
            "(APIs & Services > Credentials), download its JSON, and save it\n"
            "here as credentials.json — then run this script again."
        )
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(os.path.join(HERE, "token.json"), "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print("Saved token.json. Restart server.py to enable Gmail/Calendar tools.")


if __name__ == "__main__":
    main()
