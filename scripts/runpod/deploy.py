#!/usr/bin/env python3
"""Deploy RunPod endpoints from code configuration."""

import argparse
import hashlib
import json
import os
import sys
from typing import Any

import requests

from scripts.runpod.endpoints import ENDPOINTS
from scripts.runpod.models import EndpointConfig


class RunPodDeployer:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://rest.runpod.io/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.template_cache = {}
        self.endpoint_cache = {}

    def _get(self, path: str) -> dict[str, Any]:
        """Make GET request to RunPod API."""
        response = requests.get(f"{self.base_url}{path}", headers=self.headers)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """Make POST request to RunPod API."""
        response = requests.post(f"{self.base_url}{path}", headers=self.headers, json=data)
        response.raise_for_status()
        return response.json()

    def _put(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """Make PUT request to RunPod API."""
        response = requests.put(f"{self.base_url}{path}", headers=self.headers, json=data)
        response.raise_for_status()
        return response.json()

    def _config_hash(self, config: dict[str, Any]) -> str:
        """Generate hash of configuration for comparison."""
        # Sort keys for consistent hashing
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()

    def list_templates(self) -> dict[str, dict[str, Any]]:
        """Get all templates indexed by name."""
        if not self.template_cache:
            response = self._get("/templates")
            # Handle both list and dict responses
            templates = response if isinstance(response, list) else response.get("data", [])
            for template in templates:
                self.template_cache[template["name"]] = template
        return self.template_cache

    def list_endpoints(self) -> dict[str, dict[str, Any]]:
        """Get all endpoints indexed by name."""
        if not self.endpoint_cache:
            response = self._get("/endpoints")
            # Handle both list and dict responses
            endpoints = response if isinstance(response, list) else response.get("data", [])
            for endpoint in endpoints:
                self.endpoint_cache[endpoint["name"]] = endpoint
        return self.endpoint_cache

    def create_or_update_template(self, config: EndpointConfig, force: bool = False) -> str:
        """Create or update template, return template ID."""
        templates = self.list_templates()
        template_config = config.template.to_api_dict()

        existing = templates.get(config.template.name)

        if existing:
            # Check if update needed by comparing relevant fields
            existing_config = {k: v for k, v in existing.items() if k in template_config}

            if not force and self._config_hash(existing_config) == self._config_hash(template_config):
                print(f"✓ Template '{config.template.name}' is up to date")
                return existing["id"]

            # Update template
            print(f"↻ Updating template '{config.template.name}'...")
            template_config["id"] = existing["id"]
            updated = self._put(f"/templates/{existing['id']}", template_config)
            print(f"✓ Template updated: {updated['id']}")
            return updated["id"]
        else:
            # Create new template
            print(f"+ Creating template '{config.template.name}'...")
            created = self._post("/templates", template_config)
            print(f"✓ Template created: {created['id']}")
            return created["id"]

    def create_or_update_endpoint(self, config: EndpointConfig, template_id: str, force: bool = False):
        """Create or update endpoint."""
        endpoints = self.list_endpoints()
        endpoint_config = config.endpoint.to_api_dict()
        endpoint_config["templateId"] = template_id

        existing = endpoints.get(config.endpoint.name)

        if existing:
            # Check if update needed
            existing_config = {k: v for k, v in existing.items() if k in endpoint_config}

            if not force and self._config_hash(existing_config) == self._config_hash(endpoint_config):
                print(f"✓ Endpoint '{config.endpoint.name}' is up to date")
                return existing["id"]

            # Update endpoint
            print(f"↻ Updating endpoint '{config.endpoint.name}'...")
            endpoint_config["id"] = existing["id"]
            updated = self._put(f"/endpoints/{existing['id']}", endpoint_config)
            print(f"✓ Endpoint updated: {updated['id']}")
            return updated["id"]
        else:
            # Create new endpoint
            print(f"+ Creating endpoint '{config.endpoint.name}'...")
            created = self._post("/endpoints", endpoint_config)
            print(f"✓ Endpoint created: {created['id']}")
            return created["id"]

    def deploy(self, endpoint_name: str, force: bool = False):
        """Deploy a specific endpoint configuration."""
        if endpoint_name not in ENDPOINTS:
            raise ValueError(f"Unknown endpoint: {endpoint_name}. Available: {list(ENDPOINTS.keys())}")

        config = ENDPOINTS[endpoint_name]
        print(f"\nDeploying {endpoint_name}...")
        if force:
            print("  (Force mode - updating even if unchanged)")

        # Check if endpoint already exists
        endpoints = self.list_endpoints()
        existing_endpoint = endpoints.get(config.endpoint.name)

        if existing_endpoint and config.template.imageName == "GITHUB_TEMPLATE":
            # GitHub template - just update endpoint settings
            print(f"ℹ Using existing GitHub template (ID: {existing_endpoint['templateId']})")
            template_id = existing_endpoint["templateId"]
        else:
            # Create/update template for Docker-based deployments
            template_id = self.create_or_update_template(config, force=force)

        # Create/update endpoint
        endpoint_id = self.create_or_update_endpoint(config, template_id, force=force)

        print("\n✓ Deployment complete!")
        print(f"  Template ID: {template_id}")
        print(f"  Endpoint ID: {endpoint_id}")

    def deploy_all(self, force: bool = False):
        """Deploy all configured endpoints."""
        for name in ENDPOINTS:
            self.deploy(name, force=force)


def main():
    parser = argparse.ArgumentParser(
        description="Deploy RunPod endpoints from code configuration",
        epilog="""
This script is idempotent - it will:
  • Create templates if they don't exist
  • Update templates if configuration changed
  • Create endpoints if they don't exist  
  • Update endpoints if configuration changed
  • Do nothing if everything matches

Examples:
  # Deploy specific endpoint
  uv run --env-file=.env.local python -m yapit.runpod.deploy higgs-audio-v2
  
  # Deploy all endpoints
  uv run --env-file=.env.local python -m yapit.runpod.deploy all
  
  # Force redeploy (e.g., after code changes)
  uv run --env-file=.env.local python -m yapit.runpod.deploy higgs-audio-v2 --force
  
  # List available endpoints
  uv run --env-file=.env.local python -m yapit.runpod.deploy

Environment:
  RUNPOD_API_KEY: Your RunPod API key (required)
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "endpoint",
        nargs="?",
        choices=list(ENDPOINTS.keys()) + ["all"],
        help="Endpoint to deploy. Use 'all' to deploy all endpoints. Omit to list available endpoints.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("RUNPOD_API_KEY"),
        help="RunPod API key (default: RUNPOD_API_KEY env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deployed without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force update even if configuration hasn't changed (triggers redeploy)",
    )

    args = parser.parse_args()

    if not args.api_key:
        print("Error: RunPod API key required (--api-key or RUNPOD_API_KEY env var)")
        sys.exit(1)

    if not args.endpoint:
        print("Available endpoints:")
        for name, config in ENDPOINTS.items():
            print(f"  {name}: {config.template.name}")
        sys.exit(0)

    deployer = RunPodDeployer(args.api_key)

    if args.endpoint == "all":
        deployer.deploy_all(force=args.force)
    else:
        deployer.deploy(args.endpoint, force=args.force)


if __name__ == "__main__":
    # main()
    print("""
    This doesn't work with the Github deployment templates (yet?)... and setting up ghcr.io is a lot of overhead just for this (including way longer deploy times).
    so this is just for future reference if we decide to use registry or it becomes available
    """)
