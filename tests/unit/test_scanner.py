from obfuscator.allow import parse_allow
from obfuscator.scanner import (
    Scanner,
    binary_findings,
    case_mismatch_findings,
    leak_findings,
    path_leak_findings,
)

ALLOW_NONE = parse_allow(b"", "t")


def test_finds_any_case_with_line_numbers() -> None:
    matches = Scanner(["Pepelac"]).find("ok\nzqv pepelac\r\nPEPELAC")
    assert [(m.text, m.line) for m in matches] == [("pepelac", 2), ("PEPELAC", 3)]


def test_overlapping_matches_are_found() -> None:
    matches = Scanner(["abab"]).find("ababab")
    assert [m.start for m in matches] == [0, 2]


def test_longest_needle_at_position() -> None:
    assert Scanner(["Pep", "Pepelac"]).find("pepelac")[0].text == "pepelac"


def test_empty_scanner_finds_nothing() -> None:
    assert Scanner([]).find("anything") == []


def test_leak_findings_respect_allow_list() -> None:
    allow = parse_allow(b'[[allow]]\ntext = "max"\nfiles = ["src/**"]\n', "t")
    scanner = Scanner(["Max"])
    assert leak_findings(scanner, "max(1)", "src/a.py", allow, "E12") == []
    found = leak_findings(scanner, "max(1)", "docs/a.md", allow, "E12")
    assert [(f.code, f.line, f.text) for f in found] == [("E12", 1, "max")]


def test_path_leak_has_no_line() -> None:
    found = path_leak_findings(Scanner(["Pepelac"]), "src/pepelac.py", "src/pepelac.py", ALLOW_NONE, "E12")
    assert [(f.code, f.line, f.path) for f in found] == [("E12", None, "src/pepelac.py")]


def test_binary_search_ascii_case_insensitive() -> None:
    found = binary_findings(Scanner(["Pepelac"]), b"\x00\x01PEPELAC\xff", "a.bin")
    assert [(f.code, f.text) for f in found] == [("W01", "PEPELAC")]


def test_binary_search_non_ascii_exact() -> None:
    scanner = Scanner(["Пепелац"])
    assert binary_findings(scanner, "x Пепелац".encode(), "a.bin") != []
    assert binary_findings(scanner, "x ПЕПЕЛАЦ".encode(), "a.bin") == []


def test_binary_without_original() -> None:
    assert binary_findings(Scanner(["Pepelac"]), b"\x00\x01", "a.bin") == []


def test_alias_in_other_case_is_w11() -> None:
    aliases = frozenset({"Zqv", "zqv"})
    found = case_mismatch_findings(Scanner(aliases), aliases, "Zqv zqv ZQV zQv", "a.py")
    assert [f.text for f in found] == ["ZQV", "zQv"]
    assert {f.code for f in found} == {"W11"}


def test_word_originals_found_only_at_boundaries() -> None:
    from obfuscator.models import Rule

    scanner = Scanner.originals([Rule("sim", "qx", word=True), Rule("Pepelac", "Zqv")])
    found = scanner.find("simple service\nuse SIM_x and MySim\npepelacX")
    assert [(m.text, m.line) for m in found] == [("SIM", 2), ("Sim", 2), ("pepelac", 3)]


def test_word_aliases_exact_at_boundaries() -> None:
    from obfuscator.models import Rule

    scanner = Scanner.aliases([Rule("sim", "qx", word=True)], ignore_case=False)
    assert [m.text for m in scanner.find("aqxb qx qX")] == ["qx"]


def test_word_bytes_ascii_boundaries() -> None:
    scanner = Scanner([], words=["sim"])
    assert scanner.find_bytes(b"\x00SIM\x01simple") == [b"SIM"]
