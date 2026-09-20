## Summary

<!-- What does this change do, and why? -->

## Related issue

<!-- Closes #... -->

## Checklist

- [ ] Tests added/updated and `python -m pytest tests -W error::DeprecationWarning` passes locally
- [ ] Documentation updated (README/ARCHITECTURE/SECURITY/CONTRIBUTING) if this changes behavior, guarantees, or setup steps
- [ ] **Protected core touched?** (`fleet_manifest.yaml`, `fleetmcp/common/manifest.py`, or a `protected: true` service) — if yes, this needs CODEOWNERS approval in addition to normal review; say so explicitly here
- [ ] Secrets check: no API keys, tokens, or credentials in this diff (including test fixtures and commit messages)
- [ ] No force-push was used on this branch's history after opening the PR
