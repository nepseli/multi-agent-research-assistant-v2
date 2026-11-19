import json

from core.run_context import new_run


def test_new_run_stays_inside_base_for_path_like_topic(tmp_path):
    ctx = new_run("../../etc/passwd", base=tmp_path)
    assert tmp_path.resolve() in ctx.run_dir.resolve().parents
    assert ctx.run_dir.exists()


def test_new_run_handles_non_ascii_topic(tmp_path):
    ctx = new_run("半导体 材料 ünïcode", base=tmp_path)
    assert ctx.run_dir.exists()
    assert ctx.run_dir.name.isascii()


def test_new_runs_are_unique(tmp_path):
    a = new_run("same topic", base=tmp_path)
    b = new_run("same topic", base=tmp_path)
    assert a.run_dir != b.run_dir


def test_log_appends_json_lines(tmp_path):
    ctx = new_run("topic", base=tmp_path)
    ctx.log("stage", name="route")
    ctx.log("stage", name="research")
    lines = (ctx.run_dir / "log.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["name"] for l in lines] == ["route", "research"]
    assert json.loads(lines[0])["event"] == "stage"
