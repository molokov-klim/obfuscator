from obfuscator.changes import Changes, detect_changes


def test_no_changes() -> None:
    assert detect_changes({"a": "1"}, {"a": "1"}).empty


def test_modified_added_deleted() -> None:
    changes = detect_changes({"a": "1", "b": "2"}, {"a": "9", "c": "3"})
    assert changes == Changes(modified=("a",), added=("c",), deleted=("b",))


def test_rename_by_identical_content() -> None:
    changes = detect_changes({"old/x.py": "h1", "keep": "k"}, {"new/x.py": "h1", "keep": "k"})
    assert changes == Changes(renamed=(("old/x.py", "new/x.py"),))


def test_rename_pairs_are_deterministic() -> None:
    changes = detect_changes({"a1": "h", "a2": "h"}, {"b2": "h", "b1": "h", "b3": "h"})
    assert changes.renamed == (("a1", "b1"), ("a2", "b2"))
    assert changes.added == ("b3",)


def test_rename_and_modify_together() -> None:
    changes = detect_changes({"a": "1", "b": "2"}, {"c": "1", "b": "3"})
    assert changes == Changes(modified=("b",), renamed=(("a", "c"),))
