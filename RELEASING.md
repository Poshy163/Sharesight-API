# Releasing SharesightAPI

PyPI releases are immutable. Never reuse a version after it has been uploaded;
publish a follow-up patch instead.

## One-time trusted-publisher setup

Configure a trusted publisher for the existing
[SharesightAPI PyPI project](https://pypi.org/project/SharesightAPI/) with:

- Owner: `Poshy163`
- Repository: `Sharesight-API`
- Workflow: `publish.yml`
- Environment: `pypi`

Create a protected GitHub environment named `pypi`. Requiring approval on
that environment provides a final manual gate. The publish job uses GitHub
OIDC, so no long-lived `PYPI_API_TOKEN` secret is required.

See the
[PyPI trusted-publisher guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
for the project-side setup.

## Release checklist

1. Update the version in both `setup.py` and
   `SharesightAPI/__init__.py`.
2. Move the release notes in `CHANGELOG.md` under the new version and date.
3. Run the full local release checks:

   ```bash
   python -m pip install -r requirements_test.txt
   python -m pip install -e .
   python -m pytest
   python -m ruff check .
   python -m mypy SharesightAPI tests/typecheck_models.py
   python -m build
   python -m twine check dist/*
   python scripts/check_dist.py dist
   ```

4. Commit and push the reviewed release changes. Confirm the `Test` workflow
   succeeds on that exact commit.
5. Create a GitHub release whose tag is exactly `v<package version>`, for
   example `v1.5.0`, targeting the validated commit.
6. Publish the GitHub release. The `Publish Python package` workflow checks
   that the tag and package versions match, rebuilds the distributions, and
   publishes them through the `pypi` environment.
7. Verify the files and metadata on PyPI, then install into a clean environment:

   ```bash
   RELEASE_VERSION="$(python -c 'from SharesightAPI import __version__; print(__version__)')"
   python -m venv release-smoke
   release-smoke/bin/python -m pip install "SharesightAPI==$RELEASE_VERSION"
   release-smoke/bin/python -I -c "import SharesightAPI; print(SharesightAPI.__version__)"
   ```

   On Windows, use `release-smoke\Scripts\python.exe`.

Downstream integrations must not pin the new version until it is visible on
PyPI and the clean-install smoke test succeeds.
