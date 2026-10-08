import csv

from arena.eval import PairResult, append_log, format_matrix, git_commit, main, play_one, round_robin


def test_round_robin_counts_and_side_alternation():
    results = round_robin(["idle", "aimer", "leader"], games=10, seed=0, difficulty="normal", workers=1)
    assert [(r.a, r.b) for r in results] == [("idle", "aimer"), ("idle", "leader"), ("aimer", "leader")]
    for r in results:
        assert r.a_wins + r.b_wins + r.draws == 10
    idle_leader = results[1]
    assert idle_leader.b_wins == 10  # leader always walks up and kills idle


def test_eval_is_deterministic():
    job = ("leader", "dodger", 4, "normal")
    assert play_one(job) == play_one(job)
    a = round_robin(["aimer", "dodger"], 6, 0, "normal", workers=1)
    b = round_robin(["aimer", "dodger"], 6, 0, "normal", workers=2)
    assert a == b


def test_matrix_is_from_row_point_of_view():
    text = format_matrix(["x", "y"], [PairResult("x", "y", 7, 2, 1, 10.0)])
    x_row = next(line for line in text.splitlines() if line.startswith("x "))
    y_row = next(line for line in text.splitlines() if line.startswith("y "))
    assert "7-2-1" in x_row and x_row.endswith("70.0")
    assert "2-7-1" in y_row and y_row.endswith("20.0")


def test_log_appends_with_header_once(tmp_path):
    path = tmp_path / "log.csv"
    r = [PairResult("x", "y", 1, 2, 3, 4.0)]
    append_log(r, seed=0, games=6, difficulty="normal", path=path)
    append_log(r, seed=1, games=6, difficulty="normal", path=path)
    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 2 and rows[1]["seed"] == "1"
    assert rows[0]["commit"] == git_commit()


def test_cli_runs(capsys):
    main(["--bots", "idle,aimer", "--games", "4", "--workers", "1", "--no-log"])
    out = capsys.readouterr().out
    assert "aimer" in out and "win %" in out
