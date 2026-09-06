from app.core.rag.chunker import ParsedElement, chunk_elements, chunk_plain_text


def test_chunks_carry_breadcrumb_and_pages():
    els = [
        ParsedElement(text="Intro", element_type="heading", heading_path="1 Intro", level=1, page=1),
        ParsedElement(text="Lorem ipsum " * 40, heading_path="1 Intro", page=1),
        ParsedElement(text="Dolor sit " * 40, heading_path="1 Intro", page=2),
        ParsedElement(text="Scope", element_type="heading", heading_path="1 Intro > 1.1 Scope", level=2, page=2),
        ParsedElement(text="a | b\n1 | 2\n3 | 4", element_type="table", heading_path="1 Intro > 1.1 Scope", page=2),
    ]
    chunks = chunk_elements(els, min_chars=5)
    assert chunks, "expected chunks"
    intro = [c for c in chunks if c.heading_path == "1 Intro"]
    assert intro and intro[0].text.startswith("[1 Intro]")
    assert intro[0].page_start == 1 and intro[0].page_end == 2
    tables = [c for c in chunks if c.element_type == "table"]
    assert len(tables) == 1 and "1 | 2" in tables[0].text


def test_plain_text_fallback_splits_long_text():
    text = ("Sentence number one. " * 200).strip()
    chunks = chunk_plain_text(text, title="Doc")
    assert len(chunks) > 1
    assert all(c.chunk_index == i for i, c in enumerate(chunks))
