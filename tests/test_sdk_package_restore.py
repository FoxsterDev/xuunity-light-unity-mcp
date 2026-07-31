import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
if str(TEMPLATES_DIR) not in sys.path:
    sys.path.insert(0, str(TEMPLATES_DIR))

import server_core
import server_sdk_package_restore


class SdkPackageRestoreTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        project = root / "UnityProject"
        (project / "Assets").mkdir(parents=True)
        (project / "ProjectSettings").mkdir()
        (project / "ProjectSettings" / "ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.62f3\n",
            encoding="utf-8",
        )
        (project / "Packages").mkdir()
        (project / "Packages" / "manifest.json").write_text(
            '{"dependencies":{"com.xuunity.light-mcp":"file:../Mcp"}}\n',
            encoding="utf-8",
        )
        (project / "Packages" / "packages-lock.json").write_text(
            '{"dependencies":{"com.xuunity.light-mcp":{"version":"file:../Mcp"}}}\n',
            encoding="utf-8",
        )
        return project

    def _unity_app(self, project: Path) -> Path:
        unity_app = project.parent / "Unity.app"
        binary = unity_app / "Contents" / "MacOS" / "Unity"
        binary.parent.mkdir(parents=True)
        binary.write_text("", encoding="utf-8")
        return unity_app

    def _patch_host(self, *, project: Path, result_path: Path, receipt: dict | None):
        def fake_run(command, *, reporter, timeout_ms, last_known_output_path):
            if receipt is not None:
                bound_receipt = dict(receipt)
                run_id_index = command.index("--xuunity-package-restore-run-id") + 1
                bound_receipt.setdefault("run_id", command[run_id_index])
                bound_receipt.setdefault("project_root", str(project.resolve()))
                result_path.write_text(json.dumps(bound_receipt), encoding="utf-8")
            return 0, False

        return (
            mock.patch.object(
                server_sdk_package_restore,
                "detect_unity_app_path_for_project",
                return_value=self._unity_app(project),
            ),
            mock.patch.object(
                server_sdk_package_restore,
                "process_visibility_summary",
                return_value={"process_visibility_available": True},
            ),
            mock.patch.object(
                server_sdk_package_restore,
                "list_live_project_editor_pids",
                side_effect=[[], []],
            ),
            mock.patch.object(
                server_sdk_package_restore,
                "run_subprocess_with_progress",
                side_effect=fake_run,
            ),
            mock.patch.object(server_sdk_package_restore, "clear_stale_bridge_state", return_value={}),
        )

    def test_confirmed_receipt_is_decision_ready_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            result_path = project / "Library" / "restore.json"
            result_path.parent.mkdir(parents=True)
            receipt = {
                "schema_version": "xuunity.sdk-package-restore.v1",
                "operation": "unity.sdk.package_restore",
                "outcome": "package_restore_completed",
                "succeeded": True,
                "decision_ready": True,
                "request_status": "package_graph_registered",
                "packages": [
                    {
                        "name": "com.xuunity.light-mcp",
                        "version": "0.3.49",
                        "package_id": "com.xuunity.light-mcp@0.3.49",
                    }
                ],
                "dependency_xml_sources": [],
            }
            patches = self._patch_host(project=project, result_path=result_path, receipt=receipt)
            with patches[0], patches[1], patches[2], patches[3] as run_mock, patches[4]:
                payload = server_sdk_package_restore.run_sdk_package_restore(
                    project_root=project,
                    result_path=result_path,
                )

        self.assertTrue(payload["decision_ready"])
        self.assertEqual("package_restore_confirmed", payload["trust_class"])
        self.assertEqual("passed", payload["operator_verdict"])
        self.assertEqual(
            payload["package_files_before"]["manifest_sha256"],
            payload["package_files_after"]["manifest_sha256"],
        )
        command = run_mock.call_args.args[0]
        self.assertIn("XUUnity.LightMcp.Editor.Batch.XUUnityLightMcpBatchPackageRestoreCli.ExecuteFromCommandLine", command)
        self.assertIn("--xuunity-package-stable-idle-ticks", command)
        self.assertIn("--xuunity-package-restore-run-id", command)

    def test_missing_receipt_fails_closed_even_when_unity_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            result_path = project / "Library" / "restore.json"
            result_path.parent.mkdir(parents=True)
            patches = self._patch_host(project=project, result_path=result_path, receipt=None)
            with patches[0], patches[1], patches[2], patches[3], patches[4], mock.patch.object(
                server_sdk_package_restore, "read_recent_editor_log", return_value=[]
            ):
                payload = server_sdk_package_restore.run_sdk_package_restore(
                    project_root=project,
                    result_path=result_path,
                )

        self.assertFalse(payload["decision_ready"])
        self.assertEqual("sdk_package_restore_receipt_missing", payload["error_code"])
        self.assertEqual("package_restore_unproven", payload["trust_class"])

    def test_open_project_is_refused_before_batch_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            with (
                mock.patch.object(
                    server_sdk_package_restore,
                    "detect_unity_app_path_for_project",
                    return_value=self._unity_app(project),
                ),
                mock.patch.object(
                    server_sdk_package_restore,
                    "process_visibility_summary",
                    return_value={"process_visibility_available": True},
                ),
                mock.patch.object(
                    server_sdk_package_restore,
                    "list_live_project_editor_pids",
                    return_value=[4242],
                ),
                self.assertRaises(server_core.ToolInvocationError) as raised,
            ):
                server_sdk_package_restore.run_sdk_package_restore(project_root=project)

        self.assertEqual("editor_running_package_restore_conflict", raised.exception.code)

    def test_stale_receipt_from_another_run_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            result_path = project / "Library" / "restore.json"
            result_path.parent.mkdir(parents=True)
            receipt = {
                "schema_version": "xuunity.sdk-package-restore.v1",
                "operation": "unity.sdk.package_restore",
                "run_id": "stale-run-id",
                "project_root": str(project.resolve()),
                "succeeded": True,
                "decision_ready": True,
            }

            def fake_run(command, *, reporter, timeout_ms, last_known_output_path):
                result_path.write_text(json.dumps(receipt), encoding="utf-8")
                return 0, False

            with (
                mock.patch.object(
                    server_sdk_package_restore,
                    "detect_unity_app_path_for_project",
                    return_value=self._unity_app(project),
                ),
                mock.patch.object(
                    server_sdk_package_restore,
                    "process_visibility_summary",
                    return_value={"process_visibility_available": True},
                ),
                mock.patch.object(
                    server_sdk_package_restore,
                    "list_live_project_editor_pids",
                    side_effect=[[], []],
                ),
                mock.patch.object(
                    server_sdk_package_restore,
                    "run_subprocess_with_progress",
                    side_effect=fake_run,
                ),
            ):
                payload = server_sdk_package_restore.run_sdk_package_restore(
                    project_root=project,
                    result_path=result_path,
                )

        self.assertFalse(payload["decision_ready"])
        self.assertEqual("sdk_package_restore_receipt_identity_mismatch", payload["error_code"])

    def test_dry_run_exposes_command_without_claiming_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            with mock.patch.object(
                server_sdk_package_restore,
                "detect_unity_app_path_for_project",
                return_value=self._unity_app(project),
            ):
                payload = server_sdk_package_restore.run_sdk_package_restore(
                    project_root=project,
                    dry_run=True,
                )

        self.assertEqual("package_restore_dry_run", payload["outcome"])
        self.assertFalse(payload["decision_ready"])
        self.assertEqual("package_restore_not_run", payload["trust_class"])


if __name__ == "__main__":
    unittest.main()
