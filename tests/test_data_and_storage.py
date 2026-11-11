import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from data_processor import DataProcessor, normalize_task
from session_store import SessionStore
from trace_schema import FIELDS, evaluation, make_record, validate_record
from tools.export_jsonl import export_sessions


@pytest.fixture
def task():
    return normalize_task(dict(sample_id="test", image="folder/image.jpg", question="Where?", answer="secret",
                               source_dataset="visualprobe_train"), 0)


def test_native_visualprobe_input():
    task = normalize_task(dict(images=["VisualProbe_train/data/a.jpg"], doc_id="source-id", problem="<image>\nQ?",
                               solution="A", data_source="visual_probe_train"), 1)
    assert (task["sample_id"], task["question"], task["answer"], task["source_dataset"]) == (
        "source-id", "<image>\nQ?", "A", "visualprobe_train")


def test_legacy_vlmr1():
    item = normalize_task(dict(images=["x.jpg"], messages=[dict(role="user", content="Q"),
                                                           dict(role="assistant", content="A")]), 3)
    assert item["sample_id"] == "vlmr1_000003"
    assert item["source_format"] == "vlmr1"
    assert item["answer"] == "A"


def test_source_session_id_is_not_task_id(task, tmp_path):
    original = make_record(task, "test_idx91_v2", [], [], evaluation())
    path = tmp_path / "data.jsonl"
    path.write_text(json.dumps(original) + "\n")
    processor = DataProcessor(path)
    assert processor.load_data()
    assert processor.data[0]["sample_id"] == "test"
    assert processor.raw_data == [original]
    output, _ = SessionStore(tmp_path / "out").save(processor.data[0], 0, [], [], evaluation())
    assert output.name == "test_idx91_v3.json"


@pytest.mark.parametrize("content", ["[]", "null", "[1]", '{"image": "x.jpg"}', '{"image":"x", "question":4}'])
def test_invalid_input_reports_error(content, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(content)
    processor = DataProcessor(path)
    assert not processor.load_data()
    assert processor.error


def test_jsonl_error_has_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{}\nnot json\n')
    processor = DataProcessor(path)
    assert not processor.load_data()
    assert "第 2 行" in processor.error


def test_paths_use_dataset_parent_or_explicit_root(tmp_path):
    folder = tmp_path / "dataset"
    folder.mkdir()
    (folder / "image.jpg").touch()
    path = folder / "tasks.json"
    path.write_text(json.dumps([dict(id="x", image="image.jpg", instruction="Q")]))
    processor = DataProcessor(path)
    assert processor.load_data()
    assert processor.resolve_image() == folder / "image.jpg"
    override = tmp_path / "images"
    override.mkdir()
    (override / "image.jpg").touch()
    processor.images_root = override
    assert processor.resolve_image() == override / "image.jpg"


def test_versions_survive_restarts_and_races(task, tmp_path):
    task["_source_index"] = 4
    def save(_):
        return SessionStore(tmp_path).save(task, 4, [[1, 2, 3, 4]], [], evaluation())[0]
    first = save(0)
    before = first.read_bytes()
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(save, range(8)))
    assert len(set(paths)) == 8
    assert len(list(tmp_path.glob("*.json"))) == 9
    assert first.read_bytes() == before
    assert (tmp_path / "test_idx4_v9.json").exists()


def test_filename_cannot_escape_output(task, tmp_path):
    task["sample_id"] = "../../escape"
    path, row = SessionStore(tmp_path).save(task, 0, [], [], evaluation())
    assert path.parent == tmp_path
    assert row["sample_id"] == "../../escape"


def test_failed_validation_writes_nothing(task, tmp_path):
    with pytest.raises(ValueError):
        SessionStore(tmp_path).save(task, 0, [[1, 1, 1, 1]], [], evaluation())
    assert list(tmp_path.iterdir()) == []


def test_historical_zero_area_is_not_repaired(task):
    row = make_record(task, "test_idx0_v1", [[10, 10, 10, 10]], [], evaluation())
    original = copy.deepcopy(row)
    assert validate_record(row) == ([], ["框 0 零面积、倒置或越出原点"])
    assert validate_record(row, strict=True)[0]
    assert row == original


def test_ambiguous_and_scores():
    assert evaluation(ambiguous=True) == dict(difficulty_score=None, difficulty_level="ambiguous",
                                             is_ambiguous=True, confidence_score=None)
    for value, level in [(0, "easy"), (0.3, "easy"), (0.31, "medium"), (0.6, "medium"), (0.67, "hard")]:
        assert evaluation(value, 0.09)["difficulty_level"] == level


def test_export_keeps_all_fields_and_ignores_drafts(task, tmp_path):
    store = SessionStore(tmp_path / "output")
    for _ in range(2):
        _, row = store.save(task, 0, [[1, 2, 3, 4]], [], evaluation())
    draft = store.output_dir / ".drafts"
    draft.mkdir()
    (draft / "draft.json").write_text("{}")
    target = tmp_path / "all.jsonl"
    assert export_sessions(store.output_dir, target) == 2
    assert all(set(json.loads(line)) == FIELDS for line in target.read_text().splitlines())
    latest = tmp_path / "latest.jsonl"
    assert export_sessions(store.output_dir, latest, True) == 1
    assert json.loads(latest.read_text())["id"].endswith("_v2")
    with pytest.raises(FileExistsError):
        export_sessions(store.output_dir, target)


def test_full_release_validates_without_mutation():
    path = Path(__file__).resolve().parents[2] / "Human-Search-Traces/data/train_search_traces.jsonl"
    if not path.exists():
        pytest.skip("Published dataset is an external local checkout")
    processor = DataProcessor(path)
    assert processor.load_data()
    assert len(processor.data) == 1144
    warnings = []
    for row in processor.raw_data:
        errors, notes = validate_record(row)
        assert not errors, (row["id"], errors)
        if notes:
            warnings.append(row["id"])
    assert len(warnings) == 8  # 3 point boxes, 4 negative-edge boxes, 1 empty record.
    assert sum(len(row["events"]) for row in processor.raw_data) == 179204
