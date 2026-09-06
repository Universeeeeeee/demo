import pytest

from knowledge.citations import format_search_output, render_cited_answer
from knowledge.models import (
    CitationBinding,
    KnowledgeChunk,
    KnowledgeSource,
    RetrievalHit,
    SearchResult,
    SearchSource,
)


def _hit(chunk_id="chunk-1", url="https://example.org/paper"):
    source = KnowledgeSource(
        source_id="source-1",
        title="Paper [title]",
        url=url,
        source_format="jats_xml",
        source_kind="journal_article",
        domains=("jump",),
        authors=("A. Author",),
        year=2024,
        publisher="Example",
        license="CC BY",
        ingest_policy="full_text",
        download_url="https://example.org/paper.xml",
    )
    chunk = KnowledgeChunk(
        chunk_id=chunk_id,
        source_id=source.source_id,
        domain="jump",
        section="Methods",
        locator="Methods ¶2",
        text="Flight time is measured between take-off and landing.",
        content_digest="a" * 64,
        token_count=12,
    )
    return RetrievalHit(chunk=chunk, source=source, score=1.0)


def test_harness_style_search_output_keeps_sources_and_instruction():
    result = SearchResult(
        content="answer context",
        sources=(
            SearchSource(
                url="https://example.org/paper",
                title="Paper",
                snippet="Relevant passage",
                published_at="2024",
            ),
        ),
        truncated=False,
    )

    output = format_search_output(result)

    assert "Sources:\n- [Paper](https://example.org/paper)" in output
    assert "Relevant passage (2024)" in output
    assert output.endswith(
        "Cite the relevant URLs above as markdown links in your answer."
    )


def test_reference_renderer_resolves_bindings_deduplicates_urls_and_escapes_label():
    first = _hit()
    duplicate = _hit("chunk-2", "https://example.org/paper#methods")
    rendered = render_cited_answer(
        "结论正文。",
        (
            CitationBinding(binding_id="c1", chunk_id="chunk-1", support_type="method"),
            CitationBinding(binding_id="c2", chunk_id="chunk-2", support_type="limitation"),
        ),
        (first, duplicate),
    )

    assert rendered.count("https://example.org/paper") == 1
    assert "## 参考资料" in rendered
    assert "[Paper \\[title\\]](https://example.org/paper)" in rendered
    assert "Methods ¶2" in rendered


def test_reference_renderer_rejects_unresolved_binding():
    with pytest.raises(ValueError, match="cannot resolve chunk"):
        render_cited_answer(
            "text",
            (CitationBinding(binding_id="c1", chunk_id="missing", support_type="method"),),
            (_hit(),),
        )


def test_no_binding_never_creates_a_false_reference_section():
    assert render_cited_answer("没有足够证据回答。", (), (_hit(),)) == "没有足够证据回答。"


def test_source_contract_rejects_non_http_links():
    with pytest.raises(ValueError, match="HTTP"):
        SearchSource(url="javascript:alert(1)")
