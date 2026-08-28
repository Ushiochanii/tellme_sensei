from pathlib import Path
from packaging.requirements import Requirement


def test_numpy_is_explicit_bounded_core_dependency():
    lines = Path("requirements.txt").read_text().splitlines()
    requirement = Requirement(next(line for line in lines if line.lower().startswith("numpy")))
    assert requirement.name == "numpy"
    assert requirement.specifier.contains("1.26.0")
    assert not requirement.specifier.contains("1.25.9")
    assert requirement.specifier.contains("2.99.0")
    assert not requirement.specifier.contains("3.0.0")
