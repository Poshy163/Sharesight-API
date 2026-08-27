"""Validate built SharesightAPI wheel and source-distribution contents."""

from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9_.-]+")


def source_version() -> str:
    """Read the public version without importing runtime dependencies."""
    init_text = (PROJECT_ROOT / "SharesightAPI" / "__init__.py").read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(init_text)
    if match is None:
        raise RuntimeError("Could not find __version__ in SharesightAPI/__init__.py")
    return match.group(1)


def requirement_name(requirement: str) -> str:
    """Return a normalised distribution name from a Requires-Dist value."""
    match = REQUIREMENT_NAME.match(requirement)
    if match is None:
        raise RuntimeError(f"Could not parse Requires-Dist value: {requirement!r}")
    return match.group(0).lower().replace("_", "-")


def check_wheel(wheel: Path, expected_version: str) -> None:
    """Check wheel metadata and ensure only runtime package files are shipped."""
    if not wheel.name.endswith("-py3-none-any.whl"):
        raise RuntimeError(f"Wheel is not platform-independent: {wheel.name}")

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise RuntimeError(
                f"Expected one METADATA file in {wheel.name}, found {metadata_files}"
            )
        metadata = BytesParser(policy=compat32).parsebytes(archive.read(metadata_files[0]))

    expected_files = {
        "SharesightAPI/SharesightAPI.py",
        "SharesightAPI/__init__.py",
        "SharesightAPI/exceptions.py",
        "SharesightAPI/py.typed",
    }
    missing = expected_files - names
    if missing:
        raise RuntimeError(f"Wheel is missing package files: {sorted(missing)}")
    if any(name.startswith(("tests/", "scripts/")) for name in names):
        raise RuntimeError("Wheel unexpectedly contains development-only files")

    if metadata["Name"] != "SharesightAPI":
        raise RuntimeError(f"Unexpected package name: {metadata['Name']!r}")
    if metadata["Version"] != expected_version:
        raise RuntimeError(f"Wheel version {metadata['Version']!r} != source {expected_version!r}")
    if metadata["Requires-Python"] != ">=3.10":
        raise RuntimeError(f"Unexpected Requires-Python: {metadata['Requires-Python']!r}")

    requirements = {requirement_name(value) for value in metadata.get_all("Requires-Dist", [])}
    if requirements != {"aiofiles", "aiohttp"}:
        raise RuntimeError(f"Unexpected runtime dependencies: {sorted(requirements)}")
    if not metadata.get("License-File"):
        raise RuntimeError("Wheel metadata does not reference the bundled license")


def check_sdist(sdist: Path, expected_version: str) -> None:
    """Check that the source release contains its package and release context."""
    with tarfile.open(sdist, mode="r:gz") as archive:
        names = set(archive.getnames())

    suffixes = {
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "RELEASING.md",
        "pyproject.toml",
        "setup.py",
        "SharesightAPI/SharesightAPI.py",
        "SharesightAPI/py.typed",
        "tests/test_client.py",
    }
    missing = {
        suffix
        for suffix in suffixes
        if not any(name == suffix or name.endswith(f"/{suffix}") for name in names)
    }
    if missing:
        raise RuntimeError(f"Source distribution is missing: {sorted(missing)}")
    if expected_version not in sdist.name:
        raise RuntimeError(
            f"Source distribution name does not contain {expected_version}: {sdist.name}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dist",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "dist",
        help="directory containing exactly one wheel and one .tar.gz sdist",
    )
    args = parser.parse_args()
    wheels = sorted(args.dist.glob("*.whl"))
    sdists = sorted(args.dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(
            f"Expected one wheel and one sdist in {args.dist}; "
            f"found {len(wheels)} wheel(s), {len(sdists)} sdist(s)"
        )

    version = source_version()
    check_wheel(wheels[0], version)
    check_sdist(sdists[0], version)
    print(f"Validated SharesightAPI {version}: {wheels[0].name}, {sdists[0].name}")


if __name__ == "__main__":
    main()
