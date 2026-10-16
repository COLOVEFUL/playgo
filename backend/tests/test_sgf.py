"""SGF 写读与棋谱保存测试。"""

from playgo.rules import BLACK, WHITE
from playgo.sgf import SgfGame, parse_sgf, result_string, save_record, to_sgf_coords


def test_result_string():
    assert result_string(None, "score") == "0"
    assert result_string(BLACK, "resign") == "B+R"
    assert result_string(WHITE, "timeout") == "W+T"
    assert result_string(BLACK, "score", 3.5) == "B+3.5"
    assert result_string(WHITE, "other") == "W+?"


def test_save_record_neutral_filename(tmp_path):
    """文件名用 SGF 标准结果码（语言中立），如 001-B+R.sgf。"""
    g = SgfGame(black_name="Alice", white_name="Bob", result="B+R", moves=[(BLACK, 3 * 19 + 3)])
    p = save_record(g, tmp_path)
    assert p.name == "001-B+R.sgf"
    assert p.parent.name.startswith("20")  # YYYY-MM-DD


def test_roundtrip():
    g = SgfGame(black_name="黑方", white_name="White", result="B+3.5")
    g.moves = [(BLACK, 3 * 19 + 3), (WHITE, 15 * 19 + 15)]
    text = g.to_sgf()
    parsed = parse_sgf(text)
    assert parsed.black_name == "黑方"
    assert parsed.result == "B+3.5"
    assert parsed.moves == g.moves


def test_pass_coords():
    assert to_sgf_coords(None) == ""
