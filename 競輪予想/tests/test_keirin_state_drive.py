import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DRIVE_PATH = TOOLS / "keirin_drive_state.py"
MODULE_PATH = TOOLS / "keirin_workflow.py"

SPEC_DRIVE = importlib.util.spec_from_file_location("keirin_drive_state", DRIVE_PATH)
drive_mod = importlib.util.module_from_spec(SPEC_DRIVE)
assert SPEC_DRIVE.loader is not None
sys.modules["keirin_drive_state"] = drive_mod
SPEC_DRIVE.loader.exec_module(drive_mod)

SPEC = importlib.util.spec_from_file_location("keirin_workflow_drive_persist", MODULE_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)

FILE_ID = "test-keirin-state-file-id-not-real"


def _load_day() -> dict:
    return json.loads((ROOT / "examples" / "day_predictions.example.json").read_text(encoding="utf-8"))


def _load_results() -> dict:
    return json.loads((ROOT / "examples" / "results.example.json").read_text(encoding="utf-8"))


def _next_day(day: dict, date: str) -> dict:
    next_day = copy.deepcopy(day)
    next_day["date"] = date
    return next_day


class KeirinStateDrivePersistTest(unittest.TestCase):
    def setUp(self):
        self.day = _load_day()
        self.results = _load_results()

    def test_isolated_envs_keep_history_via_existing_drive_id(self):
        store = drive_mod.MemoryDriveStateStore({FILE_ID: b""})

        with tempfile.TemporaryDirectory() as env_a:
            state_a = Path(env_a) / "state.json"
            self.assertFalse(state_a.exists())
            workflow.run_record_predictions(
                self.day,
                state_a,
                from_drive=True,
                to_drive=True,
                drive_store=store,
                drive_file_id=FILE_ID,
            )
            self.assertTrue(state_a.exists())
            pushed_after_a = json.loads(store.files[FILE_ID].decode("utf-8"))
            self.assertEqual(len(pushed_after_a["days"]), 1)
            self.assertIsNone(pushed_after_a["days"][0]["predictions"][0]["result"])

        with tempfile.TemporaryDirectory() as env_b:
            state_b = Path(env_b) / "state.json"
            self.assertFalse(state_b.exists())
            workflow.run_record_results(
                self.results,
                state_b,
                from_drive=True,
                to_drive=True,
                drive_store=store,
                drive_file_id=FILE_ID,
            )
            saved_b = json.loads(state_b.read_text(encoding="utf-8"))
            self.assertEqual(saved_b["days"][0]["predictions"][0]["result"]["status"], "的中")
            self.assertEqual(saved_b["days"][0]["predictions"][1]["result"]["status"], "ハズレ")

        with tempfile.TemporaryDirectory() as env_c:
            state_c = Path(env_c) / "state.json"
            self.assertFalse(state_c.exists())
            next_day = _next_day(self.day, "2099-01-02")
            workflow.run_record_predictions(
                next_day,
                state_c,
                from_drive=True,
                to_drive=True,
                drive_store=store,
                drive_file_id=FILE_ID,
            )
            saved_c = json.loads(state_c.read_text(encoding="utf-8"))
            dates = [item["date"] for item in saved_c["days"]]
            self.assertEqual(dates, ["2099-01-01", "2099-01-02"])
            prev = next(item for item in saved_c["days"] if item["date"] == "2099-01-01")
            self.assertEqual(prev["predictions"][0]["result"]["status"], "的中")
            self.assertEqual(prev["predictions"][1]["result"]["trifecta"], "7-2-1")
            new = next(item for item in saved_c["days"] if item["date"] == "2099-01-02")
            self.assertIsNone(new["predictions"][0]["result"])
            remote = json.loads(store.files[FILE_ID].decode("utf-8"))
            self.assertEqual([item["date"] for item in remote["days"]], dates)
            self.assertEqual(store.upload_calls, [FILE_ID, FILE_ID, FILE_ID])

    def test_isolated_envs_accept_initial_valid_remote_state(self):
        initial = drive_mod.encode_state_bytes({"version": 1, "days": []})
        store = drive_mod.MemoryDriveStateStore({FILE_ID: initial})
        with tempfile.TemporaryDirectory() as env_a:
            workflow.run_record_predictions(
                self.day,
                Path(env_a) / "state.json",
                from_drive=True,
                to_drive=True,
                drive_store=store,
                drive_file_id=FILE_ID,
            )
        with tempfile.TemporaryDirectory() as env_b:
            workflow.run_record_results(
                self.results,
                Path(env_b) / "state.json",
                from_drive=True,
                to_drive=True,
                drive_store=store,
                drive_file_id=FILE_ID,
            )
        remote = json.loads(store.files[FILE_ID].decode("utf-8"))
        self.assertEqual(len(remote["days"]), 1)
        self.assertEqual(len(workflow.validate_state(remote)), 3)

    def test_drive_push_failure_after_upsert_stops_sheets_and_chatwork(self):
        store = drive_mod.MemoryDriveStateStore({FILE_ID: b'{"version": 1, "days": []}\n'})

        def fail_upload(file_id, content):
            raise drive_mod.DriveStateError("simulated Drive save failure")

        store.upload_replace = fail_upload  # type: ignore[method-assign]
        sheets_hook = mock.Mock()
        chatwork_hook = mock.Mock()

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with mock.patch.object(workflow, "format_predictions") as fmt:
                with mock.patch.object(workflow, "send_chatwork") as send:
                    with self.assertRaises(drive_mod.DriveStateError):
                        workflow.run_record_predictions(
                            self.day,
                            state_path,
                            from_drive=True,
                            to_drive=True,
                            drive_store=store,
                            drive_file_id=FILE_ID,
                            sheets_hook=sheets_hook,
                            chatwork_hook=chatwork_hook,
                        )
                    fmt.assert_not_called()
                    send.assert_not_called()
            self.assertTrue(state_path.exists())
        sheets_hook.assert_not_called()
        chatwork_hook.assert_not_called()

    def test_cli_isolated_envs_via_drive_flag(self):
        store = drive_mod.MemoryDriveStateStore({FILE_ID: b""})
        pred_file = ROOT / "examples" / "day_predictions.example.json"
        result_file = ROOT / "examples" / "results.example.json"
        next_day = _next_day(self.day, "2099-01-02")
        env = {drive_mod.FILE_ID_ENV: FILE_ID}

        with tempfile.TemporaryDirectory() as tmp:
            next_path = Path(tmp) / "next_day.json"
            next_path.write_text(json.dumps(next_day, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with tempfile.TemporaryDirectory() as env_a:
                state_a = Path(env_a) / "state.json"
                with mock.patch.dict(os.environ, env, clear=False):
                    with mock.patch.object(workflow.drive_state, "default_drive_store", return_value=store):
                        code_a = workflow.main(
                            [
                                "record-predictions",
                                str(pred_file),
                                "--state",
                                str(state_a),
                                "--drive",
                            ]
                        )
                self.assertEqual(code_a, 0)

            with tempfile.TemporaryDirectory() as env_b:
                state_b = Path(env_b) / "state.json"
                self.assertFalse(state_b.exists())
                with mock.patch.dict(os.environ, env, clear=False):
                    with mock.patch.object(workflow.drive_state, "default_drive_store", return_value=store):
                        code_b = workflow.main(
                            [
                                "record-results",
                                str(result_file),
                                "--state",
                                str(state_b),
                                "--from-drive",
                                "--to-drive",
                            ]
                        )
                self.assertEqual(code_b, 0)

            with tempfile.TemporaryDirectory() as env_c:
                state_c = Path(env_c) / "state.json"
                self.assertFalse(state_c.exists())
                with mock.patch.dict(os.environ, env, clear=False):
                    with mock.patch.object(workflow.drive_state, "default_drive_store", return_value=store):
                        code_c = workflow.main(
                            [
                                "record-predictions",
                                str(next_path),
                                "--state",
                                str(state_c),
                                "--drive",
                            ]
                        )
                self.assertEqual(code_c, 0)
                saved = json.loads(state_c.read_text(encoding="utf-8"))
                self.assertEqual([item["date"] for item in saved["days"]], ["2099-01-01", "2099-01-02"])
                self.assertEqual(saved["days"][0]["predictions"][1]["result"]["status"], "ハズレ")

    def test_cli_drive_push_failure_is_nonzero_and_skips_chatwork(self):
        store = drive_mod.MemoryDriveStateStore({FILE_ID: b""})
        store.upload_replace = mock.Mock(side_effect=drive_mod.DriveStateError("push failed"))

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            pred_file = ROOT / "examples" / "day_predictions.example.json"
            env = {drive_mod.FILE_ID_ENV: FILE_ID}
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(workflow.drive_state, "default_drive_store", return_value=store):
                    with mock.patch.object(workflow, "format_predictions") as fmt:
                        with mock.patch.object(workflow, "send_chatwork") as send:
                            code = workflow.main(
                                [
                                    "record-predictions",
                                    str(pred_file),
                                    "--state",
                                    str(state_path),
                                    "--from-drive",
                                    "--to-drive",
                                ]
                            )
            self.assertEqual(code, 1)
            fmt.assert_not_called()
            send.assert_not_called()

    def test_record_predictions_still_does_not_call_chatwork(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with mock.patch.object(workflow, "format_predictions") as fmt:
                with mock.patch.object(workflow, "send_chatwork") as send:
                    workflow.record_predictions(self.day, state_path)
            fmt.assert_not_called()
            send.assert_not_called()

    def test_missing_file_id_fails_closed_without_create(self):
        store = drive_mod.MemoryDriveStateStore({})
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            env = {key: "" for key in (drive_mod.FILE_ID_ENV, drive_mod.SA_JSON_ENV, drive_mod.ACCESS_TOKEN_ENV)}
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop(drive_mod.FILE_ID_ENV, None)
                with self.assertRaises(drive_mod.DriveStateError):
                    workflow.run_record_predictions(
                        self.day,
                        state_path,
                        from_drive=True,
                        to_drive=True,
                        drive_store=store,
                    )
        self.assertEqual(store.files, {})
        self.assertFalse(hasattr(drive_mod, "_drive_create"))
        self.assertFalse(hasattr(drive_mod.GoogleDriveStateStore, "create"))

    def test_unknown_file_id_does_not_create(self):
        store = drive_mod.MemoryDriveStateStore({FILE_ID: b""})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.pull_state(
                    Path(tmp) / "state.json",
                    store=store,
                    file_id="another-id-that-must-not-be-created",
                )
        self.assertEqual(list(store.files), [FILE_ID])

    def test_corrupt_remote_json_fails_without_clobbering_drive(self):
        corrupt = b"{not-json"
        store = drive_mod.MemoryDriveStateStore({FILE_ID: corrupt})
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.run_record_predictions(
                    self.day,
                    state_path,
                    from_drive=True,
                    to_drive=True,
                    drive_store=store,
                    drive_file_id=FILE_ID,
                )
            self.assertFalse(state_path.exists())
        self.assertEqual(store.files[FILE_ID], corrupt)
        self.assertEqual(store.upload_calls, [])

    def test_google_store_upload_is_patch_media_only(self):
        store = drive_mod.GoogleDriveStateStore(access_token="fake-token")
        payload = drive_mod.encode_state_bytes({"version": 1, "days": []})
        with mock.patch.object(drive_mod, "_http_request", return_value=(200, b'{"id":"x"}')) as http:
            store.upload_replace(FILE_ID, payload)
        url = http.call_args.args[0]
        self.assertEqual(http.call_args.kwargs["method"], "PATCH")
        self.assertIn("uploadType=media", url)
        self.assertIn(FILE_ID, url)
        self.assertNotIn("uploadType=multipart", url)
        self.assertTrue(url.startswith(drive_mod.DRIVE_UPLOAD_BASE + "/"))

    def test_google_store_download_uses_file_id(self):
        store = drive_mod.GoogleDriveStateStore(access_token="fake-token")
        with mock.patch.object(drive_mod, "_http_request", return_value=(200, b'{"version":1,"days":[]}')) as http:
            raw = store.download(FILE_ID)
        self.assertIn(b"version", raw)
        url = http.call_args.args[0]
        self.assertIn("alt=media", url)
        self.assertIn(FILE_ID, url)

    def test_source_never_creates_drive_files(self):
        source = DRIVE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("uploadType=multipart", source)
        self.assertNotIn("def _drive_create", source)
        self.assertNotIn("def create(", source)
        self.assertNotRegex(source, r"method\s*=\s*[\"']POST[\"'][\s\S]{0,80}DRIVE_UPLOAD_BASE")
        self.assertIn("uploadType=media", source)
        self.assertIn("PATCH", source)

    def test_scheduled_cli_requires_drive_flags_without_state(self):
        pred_file = ROOT / "examples" / "day_predictions.example.json"
        code = workflow.main(["record-predictions", str(pred_file)])
        self.assertEqual(code, 1)

    def test_cli_local_state_without_drive_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            pred_file = ROOT / "examples" / "day_predictions.example.json"
            code = workflow.main(
                ["record-predictions", str(pred_file), "--state", str(state_path)]
            )
            self.assertEqual(code, 0)
            self.assertTrue(state_path.exists())


class KeirinStateDriveMetadataSafetyTest(unittest.TestCase):
    """KEIRIN_STATE_DRIVE_FILE_ID の誤設定で別ファイルを壊さないための安全策。"""

    def setUp(self):
        self.day = _load_day()
        self.results = _load_results()

    def test_wrong_file_name_blocks_pull_without_download(self):
        store = drive_mod.MemoryDriveStateStore(
            {FILE_ID: b'{"version": 1, "days": []}\n'},
            metadata={FILE_ID: {"name": "unrelated_file.json", "mimeType": "application/json"}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.pull_state(Path(tmp) / "state.json", store=store, file_id=FILE_ID)
        self.assertEqual(store.download_calls, [])

    def test_wrong_mime_type_blocks_pull_without_download(self):
        store = drive_mod.MemoryDriveStateStore(
            {FILE_ID: b'{"version": 1, "days": []}\n'},
            metadata={
                FILE_ID: {
                    "name": drive_mod.EXPECTED_STATE_FILE_NAME,
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                }
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.pull_state(Path(tmp) / "state.json", store=store, file_id=FILE_ID)
        self.assertEqual(store.download_calls, [])

    def test_wrong_file_name_blocks_push_without_upload(self):
        store = drive_mod.MemoryDriveStateStore(
            {FILE_ID: b'{"version": 1, "days": []}\n'},
            metadata={FILE_ID: {"name": "keirin_spreadsheet.xlsx", "mimeType": "application/json"}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.push_state(Path(tmp) / "state.json", store=store, file_id=FILE_ID)
        self.assertEqual(store.upload_calls, [])
        self.assertEqual(store.download_calls, [])

    def test_wrong_mime_type_blocks_push_without_upload(self):
        store = drive_mod.MemoryDriveStateStore(
            {FILE_ID: b'{"version": 1, "days": []}\n'},
            metadata={
                FILE_ID: {"name": drive_mod.EXPECTED_STATE_FILE_NAME, "mimeType": "image/png"}
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.push_state(Path(tmp) / "state.json", store=store, file_id=FILE_ID)
        self.assertEqual(store.upload_calls, [])

    def test_correct_name_and_mime_allow_pull_and_push(self):
        store = drive_mod.MemoryDriveStateStore(
            {FILE_ID: b'{"version": 1, "days": []}\n'},
            metadata={
                FILE_ID: {"name": drive_mod.EXPECTED_STATE_FILE_NAME, "mimeType": "text/plain"}
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.pull_state(state_path, store=store, file_id=FILE_ID)
            self.assertTrue(state_path.exists())
            workflow.push_state(state_path, store=store, file_id=FILE_ID)
        self.assertEqual(store.upload_calls, [FILE_ID])

    def test_push_rejects_invalid_remote_content_even_with_correct_metadata(self):
        store = drive_mod.MemoryDriveStateStore(
            {FILE_ID: b'{"version": 1, "days": "not-a-list"}'},
        )
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.push_state(state_path, store=store, file_id=FILE_ID)
        self.assertEqual(store.upload_calls, [])
        self.assertEqual(store.files[FILE_ID], b'{"version": 1, "days": "not-a-list"}')

    def test_push_refuses_to_clear_remote_with_empty_local_state(self):
        with tempfile.TemporaryDirectory() as seed_tmp:
            seed_path = Path(seed_tmp) / "state.json"
            workflow.record_predictions(self.day, seed_path)
            remote_with_history = seed_path.read_bytes()

        store = drive_mod.MemoryDriveStateStore({FILE_ID: remote_with_history})
        with tempfile.TemporaryDirectory() as tmp:
            empty_state_path = Path(tmp) / "state.json"
            self.assertFalse(empty_state_path.exists())
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.push_state(empty_state_path, store=store, file_id=FILE_ID)
        self.assertEqual(store.upload_calls, [])
        self.assertEqual(store.files[FILE_ID], remote_with_history)

    def test_metadata_mismatch_stops_sheets_and_chatwork_on_predict(self):
        store = drive_mod.MemoryDriveStateStore(
            {FILE_ID: b'{"version": 1, "days": []}\n'},
            metadata={FILE_ID: {"name": "wrong.json", "mimeType": "application/json"}},
        )
        sheets_hook = mock.Mock()
        chatwork_hook = mock.Mock()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with mock.patch.object(workflow, "format_predictions") as fmt:
                with mock.patch.object(workflow, "send_chatwork") as send:
                    with self.assertRaises(drive_mod.DriveStateError):
                        workflow.run_record_predictions(
                            self.day,
                            state_path,
                            from_drive=True,
                            to_drive=True,
                            drive_store=store,
                            drive_file_id=FILE_ID,
                            sheets_hook=sheets_hook,
                            chatwork_hook=chatwork_hook,
                        )
                    fmt.assert_not_called()
                    send.assert_not_called()
            self.assertFalse(state_path.exists())
        sheets_hook.assert_not_called()
        chatwork_hook.assert_not_called()

    def test_metadata_mismatch_stops_sheets_on_results(self):
        store = drive_mod.MemoryDriveStateStore(
            {FILE_ID: b'{"version": 1, "days": []}\n'},
            metadata={FILE_ID: {"name": drive_mod.EXPECTED_STATE_FILE_NAME, "mimeType": "text/csv"}},
        )
        sheets_hook = mock.Mock()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with self.assertRaises(drive_mod.DriveStateError):
                workflow.run_record_results(
                    self.results,
                    state_path,
                    from_drive=True,
                    to_drive=True,
                    drive_store=store,
                    drive_file_id=FILE_ID,
                    sheets_hook=sheets_hook,
                )
        sheets_hook.assert_not_called()

    def test_google_store_get_metadata_uses_file_id_and_fields(self):
        store = drive_mod.GoogleDriveStateStore(access_token="fake-token")
        payload = b'{"name": "keirin_learning_state.json", "mimeType": "application/json"}'
        with mock.patch.object(drive_mod, "_http_request", return_value=(200, payload)) as http:
            metadata = store.get_metadata(FILE_ID)
        self.assertEqual(metadata["name"], "keirin_learning_state.json")
        self.assertEqual(metadata["mimeType"], "application/json")
        url = http.call_args.args[0]
        self.assertIn(FILE_ID, url)
        self.assertIn("fields=", url)
        self.assertNotIn("alt=media", url)


if __name__ == "__main__":
    unittest.main()
