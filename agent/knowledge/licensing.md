# Licensing

**Project license:** AGPL-3.0

**Last verified:** 2026-01-02

## Verification Commands

```bash
# Frontend license summary
cd frontend && npx license-checker --summary

# Find specific license types
npx license-checker | grep -B 1 "MPL-2.0"
npx license-checker --onlyunknown

# Python dependencies (if pip-licenses available)
pip-licenses --format=csv | grep -v "MIT\|Apache\|BSD\|ISC\|LGPL\|Unlicense\|PSF\|Python"

# Check specific packages
npm info <package> license
pip show <package> | grep -i license
```

## Findings

**Frontend (548 packages):** All AGPL-compatible
- MIT (418), ISC (61), Apache-2.0 (24), BSD (24), LGPL-3 (2)
- MPL-2.0 (3): lightningcss (build tool, no modification)
- DOMPurify: dual-licensed MPL-2.0 OR Apache-2.0 — using under Apache-2.0

**Backend:** All MIT, Apache-2.0, BSD, PSF/Python — no issues

**Key dependencies verified:**
- kokoro-js: Apache-2.0
- markitdown (Microsoft): MIT
- Stack Auth SDK: MIT

## AGPL Compatibility Notes

Compatible licenses: MIT, BSD, Apache-2.0, ISC, LGPL, PSF, AGPL, GPL-3.0

Problematic would be: GPL-2.0-only, proprietary, CDDL

MPL-2.0: Only requires source disclosure for modifications to MPL-covered files. Using as dependency without modification is fine.
