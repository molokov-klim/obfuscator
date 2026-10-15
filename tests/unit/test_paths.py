import pytest

from obfuscator.paths import PathPair, check_copy_paths, component_problem, transform_path
from obfuscator.replacer import Replacer

NAMES = Replacer({"pepelac": "zqv", "Pepelac": "Zqv"})
BAD = Replacer({"evil": "a:b", "printer": "CON"})


def test_each_component_is_replaced() -> None:
    assert transform_path("pepelac/src/Pepelac_client.py", NAMES) == "zqv/src/Zqv_client.py"


def test_extension_is_replaced() -> None:
    assert transform_path("conf.pepelac", NAMES) == "conf.zqv"


@pytest.mark.parametrize(
    "component",
    [
        "a:b",
        "a*b",
        "a?b",
        "a|b",
        'a"b',
        "a<b",
        "a>b",
        "a\tb",
        "CON",
        "con.txt",
        "LPT1.log",
        "nul",
        "end.",
        "end ",
        "x" * 256,
    ],
)
def test_invalid_components(component: str) -> None:
    assert component_problem(component) is not None


@pytest.mark.parametrize("component", ["console.py", "CONFIG", "COM10", "a b", "файл.txt", "x" * 255, ".hidden"])
def test_valid_components(component: str) -> None:
    assert component_problem(component) is None


def test_problem_created_by_replacement_is_e10() -> None:
    errors, warnings = check_copy_paths([PathPair("src/evil.py", transform_path("src/evil.py", BAD))])
    assert [f.code for f in errors] == ["E10"]
    assert warnings == []


def test_reserved_name_created_by_replacement_is_e10() -> None:
    errors, _ = check_copy_paths([PathPair("printer.txt", transform_path("printer.txt", BAD))])
    assert [f.code for f in errors] == ["E10"]


def test_problem_already_in_original_is_w02() -> None:
    errors, warnings = check_copy_paths([PathPair("a:b/pepelac.py", "a:b/zqv.py")])
    assert errors == []
    assert [f.code for f in warnings] == ["W02"]


def test_case_conflict_created_by_replacement_is_e10() -> None:
    errors, _ = check_copy_paths([PathPair("q.txt", "Q.txt"), PathPair("other.txt", "q.TXT")])
    assert [f.code for f in errors] == ["E10"]


def test_case_conflict_already_in_original_is_w02() -> None:
    errors, warnings = check_copy_paths([PathPair("Readme.md", "Readme.md"), PathPair("README.md", "README.md")])
    assert errors == []
    assert [f.code for f in warnings] == ["W02"]


def test_valid_paths_have_no_findings() -> None:
    assert check_copy_paths([PathPair("src/pepelac.py", "src/zqv.py")]) == ([], [])
