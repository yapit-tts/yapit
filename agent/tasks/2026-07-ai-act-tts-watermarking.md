---
status: backlog
scheduled: 2026-07-01
---

# AI Act Article 50: TTS Audio Watermarking

## Context

EU AI Act Article 50, binding from **August 2, 2026**, requires AI-generated audio to be marked as artificial in machine-readable format. No size exemption.

Since we self-host Kokoro, we are the "provider" — watermarking responsibility falls on us.

For InWorld (premium voices), they may handle it on their end — needs verification.

## Done when

- [ ] Check whether InWorld marks their audio output as AI-generated (ask support or check their API docs/headers)
- [ ] Research the finalized code of practice (expected mid-2026) for specific technical requirements
- [ ] Evaluate C2PA standard and alternatives for Kokoro audio output
- [ ] Implement watermarking/metadata marking for self-hosted Kokoro audio
- [ ] Add user-facing disclosure that audio is AI-generated (deployer obligation)

## References

- [EU AI Act Article 50](https://artificialintelligenceact.eu/article/50/)
- [Heuking: AI-generated content labeling](https://www.heuking.de/en/news-events/newsletter-articles/detail/ai-act-how-do-companies-need-to-label-ai-generated-content.html)
- C2PA standard: https://c2pa.org/
