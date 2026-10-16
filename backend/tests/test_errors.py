"""统一错误结构测试：稳定 code + params。"""

from playgo.errors import DownloadError, PlayGoError, err_detail, payload_of
from playgo.rules import IllegalMove


def test_playgo_error_default_code():
    e = PlayGoError("日志用中文")
    assert e.code == "error.unknown"
    assert e.params == {}
    assert str(e) == "日志用中文"


def test_illegal_move_carries_code():
    e = IllegalMove("该点已有棋子: 5", code="move.occupied", params={"point": 5})
    assert e.code == "move.occupied"
    assert e.params == {"point": 5}


def test_download_error():
    e = DownloadError("已有下载任务进行中", code="download.busy")
    assert e.code == "download.busy"


def test_err_detail_shape():
    assert err_detail("move.occupied", {"point": 3}) == {
        "code": "move.occupied",
        "args": {"point": 3},
    }
    assert err_detail("game.ended") == {"code": "game.ended", "args": {}}


def test_payload_of_fallback():
    assert payload_of(ValueError("boom")) == {
        "code": "error.unknown",
        "args": {"detail": "boom"},
    }
    e = IllegalMove("打劫", code="move.superko")
    assert payload_of(e) == {"code": "move.superko", "args": {}}


def test_params_not_conflicting_with_exception_args():
    e = PlayGoError("m", params={"x": 1})
    assert e.params == {"x": 1}
    assert e.args == ("m",)  # BaseException.args 不受影响
