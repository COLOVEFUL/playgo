"""外部棋谱导入：解析主变、编码、合法性、隔离存储与结构化错误。"""

import asyncio

import pytest
from fastapi import HTTPException, Request

from playgo import main, settings
from playgo.game import GameConfig, GameSession
from playgo.rules import BLACK, WHITE
from playgo.sgf import parse_sgf, validate_import


def request_for(*chunks):
    iterator = iter(chunks)

    async def receive():
        chunk = next(iterator, None)
        return {"type": "http.request", "body": chunk or b"", "more_body": chunk is not None}

    return Request({"type": "http", "method": "POST", "path": "/api/records/import"}, receive)


def test_import_preserves_comments_first_mainline_and_current_game(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RECORDS_DIR", tmp_path)
    app_state = main.AppState()
    app_state.game = GameSession(GameConfig())
    monkeypatch.setattr(main, "state", app_state)
    raw = (
        r"(;GM[1]SZ[9]KM[6.5]PB[黑\]方]PW[白方]C[评论 ;B[hh\] (不应落子)]"
        r" ;B[aa](;W[bb];B[])(;W[cc]))"
    ).encode()

    async def scenario():
        current = app_state.game
        first = await main.import_record(request_for(raw[:30], raw[30:]), "../../同名.SGF")
        second = await main.import_record(request_for(raw), "../../同名.SGF")
        assert first["file"] != second["file"]
        assert first["file"].startswith("imported/")
        saved = (tmp_path / first["file"]).read_text(encoding="utf-8")
        assert "不应落子" in saved
        assert ";W[cc]" in saved
        game = parse_sgf(saved)
        assert game.black_name == "黑]方"
        assert game.moves == [(BLACK, 0), (WHITE, 10), (BLACK, None)]
        detail = await main.record_detail(first["file"])
        assert detail["size"] == 9
        assert detail["komi"] == 6.5
        assert len(await main.records()) == 2
        assert app_state.game is current
        assert not app_state.review_jobs  # 打开复盘后才自动分析，导入不改对局或调度引擎

    asyncio.run(scenario())


@pytest.mark.parametrize("encoding", ["utf-8", "gb18030", "gbk"])
def test_import_encoding_roundtrip_and_escaped_values(encoding):
    text = f"(;CA[{encoding}]SZ[19]PB[黑方]PW[白方]C[CA[GBK\\]保留评论];B[pd];W[tt])"
    game, saved = validate_import(text.encode(encoding))
    assert game.black_name == "黑方"
    assert game.moves[-1] == (WHITE, None)
    assert "CA[UTF-8]" in saved
    assert "CA[GBK\\]保留评论" in saved
    assert validate_import(saved.encode("utf-8"))[0].moves == game.moves


@pytest.mark.parametrize("encoding", ["utf-8-sig", "gb18030"])
def test_import_without_encoding_declaration(encoding):
    game, saved = validate_import("(;PB[黑方];B[aa])".encode(encoding))
    assert game.black_name == "黑方"
    assert "CA[UTF-8]" in saved


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("not an sgf", "record.invalid_sgf"),
        ("(;B[aa]", "record.invalid_sgf"),
        ("(;SZ[9];B[ss])", "record.invalid_sgf"),
        ("(;KM[nan];B[aa])", "record.invalid_sgf"),
        ("(;SZ[26];B[aa])", "record.invalid_sgf"),
        ("(;B[aa];W[aa])", "record.invalid_sgf"),
        ("(;B[a])", "record.invalid_sgf"),
        ("(;CA[unknown-charset];B[aa])", "record.invalid_sgf"),
        ("(;CA[];B[aa])", "record.invalid_sgf"),
        ("(;B[aa][bb])", "record.invalid_sgf"),
        ("(;GM[2];B[aa])", "record.unsupported_sgf"),
        ("(;HA[2]AB[dd][pp];W[aa])", "record.unsupported_sgf"),
        ("(;PL[W];W[aa])", "record.unsupported_sgf"),
    ],
)
def test_invalid_import_writes_nothing(tmp_path, monkeypatch, text, code):
    monkeypatch.setattr(settings, "RECORDS_DIR", tmp_path)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.import_record(request_for(text.encode()), "test.sgf"))
    assert exc.value.status_code == 400
    assert exc.value.detail == {"code": code, "args": {}}
    assert not list(tmp_path.rglob("*"))


def test_import_size_limit_is_enforced_across_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RECORDS_DIR", tmp_path)
    monkeypatch.setattr(settings, "RECORD_IMPORT_MAX_BYTES", 16)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.import_record(request_for(b"1234567890", b"1234567890"), "test.sgf"))
    assert exc.value.status_code == 413
    assert exc.value.detail["code"] == "record.too_large"
    assert not list(tmp_path.rglob("*"))


def test_import_rejects_wrong_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RECORDS_DIR", tmp_path)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.import_record(request_for(b"(;B[aa])"), "test.txt"))
    assert exc.value.detail["code"] == "record.bad_extension"
    assert not list(tmp_path.rglob("*"))


def test_parser_chooses_first_game_and_handles_escaped_backslash():
    game = parse_sgf(r"(;PB[Black\\Name];B[aa](;W[bb])(;W[cc]))(;PB[Other];B[dd])")
    assert game.black_name == "Black\\Name"
    assert game.moves == [(BLACK, 0), (WHITE, 20)]
