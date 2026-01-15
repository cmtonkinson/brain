import uuid

from indexer import chunk_markdown, file_hash, make_point_id, markdown_blocks, split_sections


def test_split_sections_uses_primary_heading_level() -> None:
    text = "Intro line\n\n## First\nA\n\n## Second\nB"
    sections = split_sections(text)
    assert len(sections) == 2
    assert sections[0].heading == "## First"
    assert "Intro line" in sections[0].content
    assert "A" in sections[0].content
    assert sections[1].heading == "## Second"
    assert sections[1].content.strip() == "B"


def test_split_sections_falls_back_to_document() -> None:
    text = "No headings\nSecond line"
    sections = split_sections(text)
    assert len(sections) == 1
    assert sections[0].heading == "## Document"
    assert "No headings" in sections[0].content


def test_markdown_blocks_marks_code_fences_atomic() -> None:
    text = "```python\nx = 1\n```\n\nParagraph text"
    blocks = markdown_blocks(text)
    assert blocks[0].atomic is True
    assert "```python" in blocks[0].text
    assert any(not block.atomic for block in blocks)


def test_chunk_markdown_respects_token_budget() -> None:
    text = "## Heading\n\nPara one.\n\nPara two."
    chunks = chunk_markdown(text, max_tokens=100)
    assert len(chunks) == 1
    assert "Para two." in chunks[0]

    small_chunks = chunk_markdown(text, max_tokens=5)
    assert len(small_chunks) >= 2
    assert all(chunk.startswith("## Heading") for chunk in small_chunks)


def test_make_point_id_is_deterministic() -> None:
    first = make_point_id("notes/a.md", 0)
    second = make_point_id("notes/a.md", 0)
    other = make_point_id("notes/a.md", 1)
    assert first == second
    assert first != other
    uuid.UUID(first)


def test_file_hash_is_stable() -> None:
    assert file_hash("same") == file_hash("same")
    assert file_hash("same") != file_hash("different")
