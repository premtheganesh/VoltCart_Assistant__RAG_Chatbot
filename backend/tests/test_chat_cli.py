from app.graph.agent import Turn
from scripts.chat import show


def test_debug_view_handles_catalog_sources_without_a_score(capsys):
    turn = Turn(
        answer="Stride Open [2].",
        route="recommendation",
        search_query="running headphones",
        citations=[
            {
                "n": 2,
                "heading": "Stride Open (live catalog)",
                "url": None,
                "file": "catalog",
                "page": None,
            }
        ],
        sources=[
            {"n": 1, "score": 0.542, "heading": "Headphones Buying Guide"},
            {"n": 2, "score": None, "heading": "Stride Open (live catalog)"},
        ],
        top_score=0.542,
        passed_gate=True,
    )
    show(turn, debug=True)
    out = capsys.readouterr().out
    assert "[0.542] Headphones Buying Guide" in out and "[ live] Stride Open" in out
