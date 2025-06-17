# Deploying Workers to RunPod from GitHub

This guide explains how to deploy yapit TTS workers directly to RunPod's serverless infrastructure using GitHub integration.

## Prerequisites

- A [RunPod](https://runpod.io) account with credits
- A GitHub account with the yapit repository
- RunPod API key (for configuration)

## Overview

RunPod's GitHub integration allows you to:
- Build Docker images directly from your GitHub repository
- Deploy workers without manual Docker registry management
- Enable continuous deployment with GitHub pushes
- Maintain separate environments (production, staging)

## Step-by-Step Setup

### 1. Connect GitHub to RunPod

1. Go to [RunPod Settings](https://runpod.io/console/user/settings)
2. Find the **GitHub** card under **Connections**
3. Click **Connect** and authorize RunPod to access your repositories
4. Select which repositories RunPod can access (choose your yapit fork/repo)

### 2. Create a Serverless Endpoint

1. Navigate to the [Serverless section](https://www.runpod.io/console/serverless)
2. Click **New Endpoint**
3. Select **GitHub Repo** under **Custom Source**
4. Search for and select your yapit repository
5. Configure deployment options:
   - **Branch**: `main` (or your preferred branch)
   - **Dockerfile**: Path to the Dockerfile
     - For CPU: `yapit/workers/kokoro/Dockerfile.cpu`
     - For GPU: `yapit/workers/kokoro/Dockerfile.gpu`
6. Name your endpoint (e.g., `yapit-kokoro-gpu`)
7. Configure compute resources:
   - Select appropriate GPU type (for GPU deployments)
   - Set worker count and scaling parameters
8. Click **Create Endpoint**

### 3. Configure Environment Variables

After creating the endpoint, configure these environment variables in RunPod:

```bash
WORKER_ID=runpod/kokoro/gpu     # For GPU workers
# or
WORKER_ID=runpod/kokoro/cpu     # For CPU workers

DEVICE=cuda                     # or 'cpu' to match above
```

Also set the Container Start Command to:
```
python /handler.py
```

### 4. Update Your Configuration

In your yapit deployment, add the RunPod endpoint configuration:

#### For docker-compose.runpod.yml:
```yaml
services:
  runpod-bridge:
    environment:
      - RUNPOD_API_KEY=${RUNPOD_API_KEY}
      - RUNPOD_ENDPOINT_KOKORO_GPU=<your-endpoint-id>
      # Add more endpoints as needed
```

#### In your .env file:
```bash
RUNPOD_API_KEY=your_api_key_here
```

## Model Weight Optimization

The Dockerfiles are configured to download and cache model weights during build time. This significantly reduces cold start times by:

1. Downloading the Kokoro model from HuggingFace during build
2. Caching all voice files locally in the image
3. Setting `HF_HUB_OFFLINE=1` to prevent runtime downloads

This approach ensures:
- Faster worker startup times
- No dependency on external services during runtime
- Consistent performance across all worker instances

## Build Process and Monitoring

### Build Status

Monitor your build progress in the **Builds** tab of your endpoint:

| Status    | Description                            |
|-----------|----------------------------------------|
| Pending   | Build is queued                        |
| Building  | Docker image is being built            |
| Uploading | Image is uploading to RunPod registry  |
| Testing   | RunPod is testing the worker           |
| Completed | Build successful and deployed          |
| Failed    | Build failed (check logs)              |

### Build Constraints

Be aware of RunPod's limitations:
- **Build time limit**: 160 minutes
- **Image size limit**: 100 GB
- **No GPU access during build**
- **No private base images**

## Continuous Deployment

To enable automatic deployments:

1. Push changes to your configured branch
2. RunPod automatically detects changes and rebuilds
3. New workers deploy with zero downtime

## Multi-Environment Setup

For staging and production environments:

1. Create separate endpoints for each environment
2. Configure different branches:
   - Production: `main` branch
   - Staging: `develop` branch
3. Clone endpoints to maintain consistent settings

## Troubleshooting

### Common Issues

1. **Build timeouts**: Optimize Dockerfile to reduce build time
2. **Large image size**: Remove unnecessary dependencies
3. **Worker fails to start**: Check endpoint logs in RunPod console
4. **Model loading errors**: Verify environment variables and cached paths

### Debugging Steps

1. Check build logs in the RunPod console
2. Verify environment variables are set correctly
3. Test Docker image locally before deploying
4. Ensure handler.py is correctly placed at `/handler.py`

## Cost Optimization

- Use appropriate GPU types for your workload
- Configure auto-scaling based on demand
- Monitor usage in RunPod dashboard
- Consider CPU workers for light workloads

## Security Considerations

- Store RunPod API keys securely
- Use environment variables for sensitive data
- Regularly rotate API keys
- Monitor endpoint access logs

## Next Steps

- Set up monitoring and alerts
- Configure auto-scaling policies
- Implement health checks
- Create backup deployment strategies