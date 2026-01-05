#!/usr/bin/env python3
"""Deploy RunPod endpoints from code configuration.

Uses raw GraphQL - the SDK is too limited for idempotent updates.
"""

import argparse
import os
import sys

import runpod
from runpod.api.graphql import run_graphql_query

from infra.runpod.endpoints import ENDPOINTS
from infra.runpod.models import RunPodEndpoint


def get_templates() -> dict[str, dict]:
    """Get all templates via GraphQL."""
    query = """
    query {
      myself {
        podTemplates {
          id
          name
          imageName
          dockerArgs
          containerDiskInGb
          env { key value }
          isServerless
        }
      }
    }
    """
    result = run_graphql_query(query)
    templates = result.get("data", {}).get("myself", {}).get("podTemplates", [])
    return {t["name"]: t for t in templates}


def get_endpoints() -> dict[str, dict]:
    """Get all endpoints via GraphQL."""
    query = """
    query {
      myself {
        endpoints {
          id
          name
          templateId
          gpuIds
          workersMin
          workersMax
          idleTimeout
          scalerType
          scalerValue
        }
      }
    }
    """
    result = run_graphql_query(query)
    endpoints = result.get("data", {}).get("myself", {}).get("endpoints", [])
    return {e["name"]: e for e in endpoints}


def save_template(
    name: str,
    image_name: str,
    docker_start_cmd: str | None = None,
    container_disk_in_gb: int = 10,
    env: dict[str, str] | None = None,
    is_serverless: bool = True,
    template_id: str | None = None,
) -> str:
    """Create or update a template via GraphQL saveTemplate mutation."""
    input_fields = [f'name: "{name}"', f'imageName: "{image_name}"']

    if template_id:
        input_fields.append(f'id: "{template_id}"')

    if docker_start_cmd:
        escaped_cmd = docker_start_cmd.replace('"', '\\"')
        input_fields.append(f'dockerArgs: "{escaped_cmd}"')
    else:
        input_fields.append('dockerArgs: ""')

    input_fields.append(f"containerDiskInGb: {container_disk_in_gb}")
    input_fields.append("volumeInGb: 0")
    input_fields.append('ports: ""')

    if env:
        env_pairs = ", ".join(f'{{ key: "{k}", value: "{v}" }}' for k, v in env.items())
        input_fields.append(f"env: [{env_pairs}]")
    else:
        input_fields.append("env: []")

    input_fields.append(f"isServerless: {'true' if is_serverless else 'false'}")
    input_fields.append('containerRegistryAuthId: ""')
    input_fields.append("startSsh: true")
    input_fields.append("isPublic: false")
    input_fields.append('readme: ""')

    mutation = f"""
    mutation {{
        saveTemplate(input: {{ {", ".join(input_fields)} }}) {{
            id
            name
        }}
    }}
    """

    result = run_graphql_query(mutation)
    if "errors" in result:
        raise RuntimeError(f"GraphQL error: {result['errors']}")

    return result["data"]["saveTemplate"]["id"]


def save_endpoint(
    name: str,
    template_id: str,
    endpoint_cfg: RunPodEndpoint,
    endpoint_id: str | None = None,
) -> str:
    """Create or update an endpoint via GraphQL saveEndpoint mutation."""
    input_fields = [
        f'name: "{name}"',
        f'templateId: "{template_id}"',
    ]

    if endpoint_id:
        input_fields.append(f'id: "{endpoint_id}"')

    # GPU configuration
    if endpoint_cfg.gpuTypeIds:
        gpu_str = ",".join(endpoint_cfg.gpuTypeIds)
        input_fields.append(f'gpuIds: "{gpu_str}"')
    else:
        input_fields.append('gpuIds: "AMPERE_16"')

    if endpoint_cfg.gpuCount > 1:
        input_fields.append(f"gpuCount: {endpoint_cfg.gpuCount}")

    # Scaling config
    input_fields.append(f"workersMin: {endpoint_cfg.workersMin}")
    input_fields.append(f"workersMax: {endpoint_cfg.workersMax}")
    input_fields.append(f"idleTimeout: {endpoint_cfg.idleTimeout}")
    input_fields.append(f'scalerType: "{endpoint_cfg.scalerType}"')
    input_fields.append(f"scalerValue: {endpoint_cfg.scalerValue}")

    # Network volume (empty = no volume)
    input_fields.append('networkVolumeId: ""')
    input_fields.append('locations: ""')

    mutation = f"""
    mutation {{
        saveEndpoint(input: {{ {", ".join(input_fields)} }}) {{
            id
            name
        }}
    }}
    """

    result = run_graphql_query(mutation)
    if "errors" in result:
        raise RuntimeError(f"GraphQL error: {result['errors']}")

    return result["data"]["saveEndpoint"]["id"]


class RunPodDeployer:
    def __init__(self, image_tag: str):
        self._templates: dict[str, dict] | None = None
        self._endpoints: dict[str, dict] | None = None
        self.image_tag = image_tag

    @property
    def templates(self) -> dict[str, dict]:
        if self._templates is None:
            self._templates = get_templates()
        return self._templates

    @property
    def endpoints(self) -> dict[str, dict]:
        if self._endpoints is None:
            self._endpoints = get_endpoints()
        return self._endpoints

    def deploy(self, endpoint_name: str) -> None:
        if endpoint_name not in ENDPOINTS:
            available = ", ".join(ENDPOINTS.keys())
            raise ValueError(f"Unknown endpoint: {endpoint_name}. Available: {available}")

        config = ENDPOINTS[endpoint_name]
        print(f"\nDeploying {endpoint_name}...")

        # Template
        template_cfg = config.template
        existing_template = self.templates.get(template_cfg.name)

        docker_cmd = None
        if template_cfg.dockerStartCmd:
            docker_cmd = " ".join(template_cfg.dockerStartCmd)

        # Append tag to image name
        image_name = f"{template_cfg.imageName}:{self.image_tag}"

        if existing_template:
            print(f"  ↻ Updating template '{template_cfg.name}'...")
            print(f"    Image: {image_name}")
            template_id = save_template(
                name=template_cfg.name,
                image_name=image_name,
                docker_start_cmd=docker_cmd,
                container_disk_in_gb=template_cfg.containerDiskInGb,
                env=template_cfg.env,
                is_serverless=template_cfg.isServerless,
                template_id=existing_template["id"],
            )
        else:
            print(f"  + Creating template '{template_cfg.name}'...")
            print(f"    Image: {image_name}")
            template_id = save_template(
                name=template_cfg.name,
                image_name=image_name,
                docker_start_cmd=docker_cmd,
                container_disk_in_gb=template_cfg.containerDiskInGb,
                env=template_cfg.env,
                is_serverless=template_cfg.isServerless,
            )
        print(f"  ✓ Template: {template_id}")

        # Endpoint
        endpoint_cfg = config.endpoint
        # RunPod adds " -fb" suffix when Flashboot is enabled in UI
        existing_endpoint = self.endpoints.get(endpoint_cfg.name) or self.endpoints.get(endpoint_cfg.name + " -fb")

        if existing_endpoint:
            print(f"  ↻ Updating endpoint '{existing_endpoint['name']}'...")
            endpoint_id = save_endpoint(
                name=existing_endpoint["name"],  # preserve existing name (may have -fb suffix)
                template_id=template_id,
                endpoint_cfg=endpoint_cfg,
                endpoint_id=existing_endpoint["id"],
            )
        else:
            print(f"  + Creating endpoint '{endpoint_cfg.name}'...")
            endpoint_id = save_endpoint(
                name=endpoint_cfg.name,
                template_id=template_id,
                endpoint_cfg=endpoint_cfg,
            )

        print(f"  ✓ Endpoint: {endpoint_id}")

        print("\n✓ Deployment complete!")
        print(f"  Console: https://console.runpod.io/serverless/user/endpoint/{endpoint_id}")
        print("\n  ⚠ Manual steps (not available via API):")
        print("    1. Enable Flashboot")
        if endpoint_cfg.model:
            print(f"    2. Set Model cache: {endpoint_cfg.model}")

    def deploy_all(self) -> None:
        for name in ENDPOINTS:
            self.deploy(name)


def main():
    parser = argparse.ArgumentParser(description="Deploy RunPod endpoints")
    parser.add_argument(
        "endpoint",
        nargs="?",
        choices=list(ENDPOINTS.keys()) + ["all"],
        help="Endpoint to deploy (omit to list available)",
    )
    parser.add_argument("--api-key", default=os.environ.get("RUNPOD_API_KEY"))
    parser.add_argument("--image-tag", required=True, help="Docker image tag (e.g., sha-abc123)")

    args = parser.parse_args()

    if not args.endpoint:
        print("Available endpoints:")
        for name, config in ENDPOINTS.items():
            print(f"  {name}: {config.template.name}")
        return

    if not args.api_key:
        print("Error: RUNPOD_API_KEY required (env var or --api-key)")
        sys.exit(1)

    runpod.api_key = args.api_key

    deployer = RunPodDeployer(image_tag=args.image_tag)
    if args.endpoint == "all":
        deployer.deploy_all()
    else:
        deployer.deploy(args.endpoint)


if __name__ == "__main__":
    main()
