
TLDR: We only have kokoro-cpu in runpod for now, as the serverless capacity overflow endpoint. We abandoned IaC for runpod because their API & co is shit and it's less work for me manually pressing a few buttons in their UI for this one endpoint rather than managing it via IaC through agents.
Queue based scaling. cpu3c (3ghz compute optimized, 4vcpus, 8GB RAM)
Worker timeout 60s because requests arrive in bursts. Might even want to set it higher.
