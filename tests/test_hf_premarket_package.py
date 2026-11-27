"""The public reference is a single reviewed exception, not a raw-data bundle."""
import pytest

from scripts import package_hf_space as package


def test_reviewed_reference_is_the_only_packaged_json_input():
    json_sources = [src for src, _ in package.SOURCES if src.endswith(".json")]
    assert json_sources == [package.PUBLIC_PREMARKET_REFERENCE]
    assert all(not src.startswith(("data/", "state/", "runs/")) for src, _ in package.SOURCES)
    assert not any("collect_premarket" in src or "build_premarket" in src for src, _ in package.SOURCES)


def test_reviewed_reference_passes_and_modified_data_fails():
    raw = (package.ROOT / package.PUBLIC_PREMARKET_REFERENCE).read_bytes()
    package._validate_text(package.PUBLIC_PREMARKET_REFERENCE, raw)
    with pytest.raises(package.PackagingError, match="audited hash"):
        package._validate_text(package.PUBLIC_PREMARKET_REFERENCE, raw + b"\n")
    with pytest.raises(package.PackagingError, match="audited hash"):
        package._validate_text(package.PUBLIC_PREMARKET_REFERENCE, b'{"open": 100, "volume": 50}')
