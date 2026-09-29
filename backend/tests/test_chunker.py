"""Chunker seam: pure functions for token counts, overlap, and page mapping."""
import pytest

from app.chunker import chunk_pages, parse_pdf, strip_annexes

# Exact word counter so token budgets are deterministic in tests. Production
# uses the default ~4-chars-per-token heuristic.
def count_words(text: str) -> int:
    return len(text.split())


def test_chunks_come_in_under_budget_with_word_overlap() -> None:
    """Windows stay within max_tokens and consecutive chunks share their tail."""
    page = " ".join(f"word{i}" for i in range(1200))

    chunks = chunk_pages(
        [page], source="corpus.pdf", max_tokens=100, overlap_tokens=20,
        count_tokens=count_words,
    )

    assert all(count_words(c.text) <= 100 for c in chunks)
    assert len(chunks) >= 3  # 1200 words / 100 per window
    tail = " ".join(chunks[0].text.split()[-20:])
    assert chunks[1].text.startswith(tail)


def test_a_single_word_over_budget_still_becomes_a_chunk() -> None:
    """Progress is guaranteed even when one token exceeds the whole budget."""
    chunks = chunk_pages(
        ["tiny " + "supercalifragilistic" * 1], source="corpus.pdf",
        max_tokens=1, overlap_tokens=0, count_tokens=count_words,
    )

    assert [c.text for c in chunks] == ["tiny", "supercalifragilistic"]


def test_page_mapping_and_indices_survive_splitting() -> None:
    """Every Chunk knows its Document, the page it starts on, and its position."""
    page1 = " ".join(f"w{i}" for i in range(120))
    page2 = ""  # blank page contributes nothing
    page3 = " ".join(f"p3-{i}" for i in range(120))

    chunks = chunk_pages(
        [page1, page2, page3], source="ai-act.pdf",
        max_tokens=100, overlap_tokens=20, count_tokens=count_words,
    )

    assert all(c.source == "ai-act.pdf" for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].page == 1
    assert any(c.page == 3 for c in chunks)  # later windows land on page 3


def test_a_chunk_spanning_pages_records_its_starting_page() -> None:
    """A window straddling a page boundary cites the page it starts on."""
    page1 = " ".join(f"a{i}" for i in range(90))
    page2 = " ".join(f"b{i}" for i in range(90))

    chunks = chunk_pages(
        [page1, page2], source="ai-act.pdf",
        max_tokens=100, overlap_tokens=20, count_tokens=count_words,
    )

    spanning = [c for c in chunks if c.text.startswith("a") and " b" in c.text]
    assert spanning, "expected at least one chunk to straddle the boundary"
    assert all(c.page == 1 for c in spanning)


def test_annex_pages_are_excluded_from_the_regulation_body() -> None:
    """Everything from the first ANNEX heading page onward is dropped."""
    pages = [
        "Article 1 Subject matter",
        "Article 2 Definitions",
        "ANNEX I\nIntegrated framework description",
        "ANNEX II\nTechnical documentation",
    ]

    assert strip_annexes(pages) == ["Article 1 Subject matter", "Article 2 Definitions"]


def test_a_corpus_without_annexes_is_returned_intact() -> None:
    """No annex headings means every page stays, TOC-style mentions included."""
    pages = ["Contents ... Annex I on page 100", "Article 1 Subject matter"]

    assert strip_annexes(pages) == pages


def test_body_text_sharing_a_page_with_the_annex_heading_survives() -> None:
    """The cut is at the heading, not the page: earlier articles on it are kept."""
    pages = [
        "Article 99 Penalties",
        "Article 100 Entry into force\nANNEX I\nFramework description",
    ]

    assert strip_annexes(pages) == ["Article 99 Penalties", "Article 100 Entry into force"]


def test_a_heading_merged_with_its_title_by_extraction_still_cuts() -> None:
    """pypdf often renders 'ANNEX I Title' on one extracted line; the cut still fires."""
    pages = ["Article 1 Subject matter", "ANNEX I Integrated framework description"]

    assert strip_annexes(pages) == ["Article 1 Subject matter"]


def _build_pdf(page_texts: list[str]) -> bytes:
    """A minimal but valid one-font PDF with one text object per page."""
    objects: list[bytes] = []
    page_ids = [3 + 2 * k for k in range(len(page_texts))]
    font_id = 3 + 2 * len(page_texts)
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode())
    for pid, text in zip(page_ids, page_texts):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {pid + 1} 0 R >>".encode()
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n{content.decode()}\nendstream".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    return bytes(out)


def test_parse_pdf_extracts_text_page_by_page(tmp_path) -> None:
    """pypdf gives one text string per page, in page order."""
    pdf_path = tmp_path / "tiny.pdf"
    pdf_path.write_bytes(_build_pdf(["Article 1 text", "Article 2 text"]))

    pages = parse_pdf(pdf_path)

    assert len(pages) == 2
    assert "Article 1 text" in pages[0]
    assert "Article 2 text" in pages[1]


def test_default_token_counter_keeps_prose_sized_like_the_spec() -> None:
    """The chars-per-token heuristic alone lands chunks near the ~500-token target."""
    page = " ".join("legal prose word" for _ in range(2000))

    chunks = chunk_pages([page], source="corpus.pdf")

    assert len(chunks) >= 3
    assert all(len(c.text) <= 4 * 500 + 20 for c in chunks)
    words0, words1 = chunks[0].text.split(), chunks[1].text.split()
    overlap = next(
        k for k in range(min(len(words0), len(words1)), 0, -1) if words0[-k:] == words1[:k]
    )
    assert overlap >= 10  # ~80 heuristic tokens ≈ 50+ words of shared context


def test_the_final_window_is_not_re_emitted_as_near_duplicates() -> None:
    """Once the last window reaches the end, chunking stops — no repeated tails."""
    page = " ".join(f"w{i}" for i in range(120))

    chunks = chunk_pages(
        [page], source="corpus.pdf", max_tokens=100, overlap_tokens=20,
        count_tokens=count_words,
    )

    assert len(chunks) == 2  # [0:100] and [80:120], not a tail of duplicates
    assert count_words(chunks[1].text) == 40


def test_an_overlap_at_or_above_the_budget_fails_loudly() -> None:
    """overlap >= max would slide one word at a time; config errors must be loud."""
    page = " ".join(f"w{i}" for i in range(120))

    with pytest.raises(ValueError):
        chunk_pages([page], source="corpus.pdf", max_tokens=100, overlap_tokens=100,
                    count_tokens=count_words)
