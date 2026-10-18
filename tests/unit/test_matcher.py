import pytest

from obfuscator.matcher import Matcher, char_kind, left_boundary, right_boundary


def _hits(keys: dict[str, bool], text: str) -> list[tuple[int, str]]:
    return [(hit.start, hit.key) for hit in Matcher(keys).iter_hits(text)]


@pytest.mark.parametrize(
    "text",
    ["sim", "sim-x", "_sim#", "sim2", "sim_client", "a.sim.b", "x/sim/y", "simClient", "(sim)", "Ssim".lower()[1:]],
)
def test_lowercase_word_found_at_boundary(text: str) -> None:
    assert [key for _, key in _hits({"sim": True}, text)] == ["sim"]


@pytest.mark.parametrize("text", ["simple", "assimilate", "isim", "simsim"])
def test_lowercase_word_not_found_inside_word(text: str) -> None:
    assert _hits({"sim": True}, text) == []


@pytest.mark.parametrize("text", ["MySim", "SimRunner", "mySimRunner", "Sim", "Sim_x"])
def test_capitalized_word_with_camel_boundaries(text: str) -> None:
    assert [key for _, key in _hits({"Sim": True}, text)] == ["Sim"]


@pytest.mark.parametrize("text", ["Simulator", "MYSim"])
def test_capitalized_word_not_found(text: str) -> None:
    assert _hits({"Sim": True}, text) == []


def test_upper_word() -> None:
    # xSIM — переход регистра строчная → заглавная, это граница
    assert [start for start, _ in _hits({"SIM": True}, "SIM_X SIM-2 SIMPLE xSIM")] == [0, 6, 20]
    assert _hits({"SIM": True}, "SIMClient") == []  # слитная аббревиатура не распознаётся (принятый риск)


def test_cyrillic_boundaries() -> None:
    assert [key for _, key in _hits({"вий": True}, "вий-1 Вийка вийка мойВий")] == ["вий"]
    assert [key for _, key in _hits({"Вий": True}, "мойВий Вийка")] == ["Вий"]


def test_substring_rule_ignores_boundaries() -> None:
    assert [key for _, key in _hits({"sim": False}, "simple")] == ["sim"]


def test_longest_valid_key_wins() -> None:
    keys = {"sim": True, "simple": True}
    assert _hits(keys, "simple") == [(0, "simple")]
    assert _hits(keys, "simplex") == []
    assert _hits({"sim": True, "simp": False}, "simple") == [(0, "simp")]
    assert _hits({"sim": False, "simple": True}, "simplex") == [(0, "sim")]


def test_overlapping_scan() -> None:
    hits = list(Matcher({"aba": False}).iter_hits("ababa", overlapping=True))
    assert [hit.start for hit in hits] == [0, 2]


def test_boundary_helpers_and_kinds() -> None:
    assert left_boundary("x", 0)
    assert right_boundary("x", 1)
    assert not left_boundary("ab", 1)
    assert left_boundary("aB", 1)
    assert char_kind("a") == "lower"
    assert char_kind("Я") == "upper"
    assert char_kind("1") == "other"
    assert char_kind("中") == "letter"


def test_ascii_only_boundaries() -> None:
    text = "\xe9sim"  # é в latin-1 — не буква ASCII, значит граница
    assert [hit.key for hit in Matcher({"sim": True}, ascii_only=True).iter_hits(text)] == ["sim"]
    assert list(Matcher({"sim": True}).iter_hits(text)) == []
