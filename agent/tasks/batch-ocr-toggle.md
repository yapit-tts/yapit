---
status: done
type: implementation
---

# Task: Batch OCR Settings Toggle

## Goal

Add a user setting to opt into slower batch OCR processing in exchange for 2x page limit.

## Current State

`_batch_ocr` function already exists in `yapit/gateway/processors/document/mistral.py:110` but isn't wired up. TODO on line 107 confirms this.

## Next Steps

1. Review how batch vs single OCR differs (page limits, latency, API differences)
2. Wire `_batch_ocr` into `MistralOCRProcessor` with a flag to select mode
3. Add frontend settings toggle with tooltip explaining tradeoff
4. Test both paths work correctly
