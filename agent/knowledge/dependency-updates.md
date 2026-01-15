# Dependency Updates

## Version-Specific Checklists

### Stack Auth (`docker/Dockerfile.stackauth`)

- [ ] Is the profile image section still hidden in AccountSettings? We use CSS selector `div.flex.flex-col.sm\:flex-row.gap-2:has(span.rounded-full)` to hide it (no S3 configured).

## Adding New Dependencies

When adding new packages, verify license compatibility with AGPL-3.0. See [[licensing]] for verification commands and compatible licenses.
