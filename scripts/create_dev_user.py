#!/usr/bin/env python3
"""Create a development test user in stack-auth."""

import os
import sys
import time

import requests


def wait_for_stack_auth(api_host: str, max_attempts: int = 30):
    """Wait for stack-auth to be ready."""
    print(f"Waiting for stack-auth at {api_host}...")
    for i in range(max_attempts):
        try:
            r = requests.get(f"{api_host}/health", timeout=1)
            if r.status_code == 200:
                print("Stack-auth is ready!")
                return True
        except Exception as e:
            if i == 0:
                print(f"Connection error: {e}")
        time.sleep(1)
    return False


def create_dev_user():
    """Create a test user for development."""
    api_host = os.getenv("DEV_STACK_AUTH_API_HOST", "http://localhost:8102")
    project_id = os.getenv("STACK_AUTH_PROJECT_ID")
    server_key = os.getenv("STACK_AUTH_SERVER_KEY")

    if not project_id or not server_key:
        print("Error: STACK_AUTH_PROJECT_ID and STACK_AUTH_SERVER_KEY must be set")
        sys.exit(1)

    # Wait for stack-auth
    if not wait_for_stack_auth(api_host):
        print("Error: Stack-auth not responding")
        sys.exit(1)

    # Fixed dev user credentials
    dev_email = "dev@example.com"
    dev_password = "dev-password-123"

    headers = {
        "X-Stack-Access-Type": "server",
        "X-Stack-Project-Id": project_id,
        "X-Stack-Secret-Server-Key": server_key,
    }

    print(f"Using project_id: {project_id}")
    print(f"Using server_key: {server_key[:10]}...")

    # Try to create user (might already exist)
    r = requests.post(
        f"{api_host}/api/v1/users",
        headers=headers,
        json={
            "primary_email": dev_email,
            "password": dev_password,
            "primary_email_verified": True,
            "primary_email_auth_enabled": True,
            "display_name": "Dev User",
            "server_metadata": {"is_admin": True},
        },
    )

    if r.status_code in [200, 201]:
        user_id = r.json()["id"]
        print(f"User created with ID: {user_id}")
    elif (r.status_code == 400 and "already exists" in r.text) or (r.status_code == 409):
        print(f"User already exists: {dev_email}")
    else:
        print(f"Error creating user: {r.status_code} {r.text}")
        sys.exit(1)

    print(f"Dev user ready: {dev_email} / {dev_password}")


if __name__ == "__main__":
    create_dev_user()
