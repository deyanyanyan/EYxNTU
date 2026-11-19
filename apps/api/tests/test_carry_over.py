"""Re-ingesting a source keeps the course's references to it (app/core/rag/carry_over.py)."""
from app.core.rag.carry_over import ids_in, match_chunks, swap_ids

OLD_A, OLD_B, OLD_C = "00000000-0000-0000-0000-00000000000a", "00000000-0000-0000-0000-00000000000b", "00000000-0000-0000-0000-00000000000c"
NEW_A, NEW_B = "11111111-0000-0000-0000-00000000000a", "11111111-0000-0000-0000-00000000000b"


def test_unchanged_text_maps_to_the_new_chunk_even_if_reflowed():
    retired = [(OLD_A, 0, "Report within 1 hour."), (OLD_B, 1, "Passwords need 14\ncharacters."), (OLD_C, 2, "Old rule, since removed.")]
    live = [(NEW_A, 0, "Report within 1 hour."), (NEW_B, 1, "Passwords need 14 characters.")]
    assert match_chunks(retired, live) == {OLD_A: NEW_A, OLD_B: NEW_B}


def test_repeated_text_maps_to_the_nearest_position():
    retired = [("old-1", 1, "Confidential"), ("old-9", 9, "Confidential")]
    live = [("new-0", 0, "Confidential"), ("new-10", 10, "Confidential")]
    assert match_chunks(retired, live) == {"old-1": "new-0", "old-9": "new-10"}


def test_every_reference_in_course_content_moves():
    content = {
        "slides": [{"id": "s1", "bullets": ["Report within 1 hour [1]"]}],
        "references": {"1": {"chunk_id": OLD_A, "source": "handbook.md"}, "2": {"chunk_id": OLD_C}},
        "questions": [{"stem": "When?", "chunk_id": OLD_A, "source_span": "Report within 1 hour."}],
    }
    new, changed = swap_ids(content, {OLD_A: NEW_A})
    assert changed
    assert new["references"]["1"]["chunk_id"] == NEW_A and new["questions"][0]["chunk_id"] == NEW_A
    assert new["references"]["2"]["chunk_id"] == OLD_C          # changed passage: still cited, kept retired
    assert new["slides"] == content["slides"]
    assert content["references"]["1"]["chunk_id"] == OLD_A      # the original is not mutated in place


def test_lesson_and_objective_chunk_lists_move():
    assert swap_ids([OLD_A, OLD_B], {OLD_A: NEW_A}) == ([NEW_A, OLD_B], True)
    objectives = [{"id": "O1", "text": "Report on time", "source_chunk_ids": [OLD_B]}]
    assert swap_ids(objectives, {OLD_A: NEW_A}) == (objectives, False)


def test_finds_which_retired_chunks_are_still_used():
    content = {"references": {"2": {"chunk_id": OLD_C}}, "note": f"mentions {OLD_B} inside text"}
    assert ids_in(content, {OLD_A, OLD_B, OLD_C}) == {OLD_C}
    assert ids_in([], {OLD_A}) == set() and ids_in(None, {OLD_A}) == set()
