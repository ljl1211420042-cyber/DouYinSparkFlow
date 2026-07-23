import unittest
from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/schedule.yml")


class CookieStateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_manual_dispatch_exposes_validation_only_mode(self):
        self.assertIn("validate_only:", self.workflow)
        self.assertIn("type: boolean", self.workflow)
        self.assertIn("VALIDATE_ONLY:", self.workflow)
        self.assertIn("inputs.validate_only", self.workflow)

    def test_serializes_runs_without_cancelling_active_send(self):
        self.assertIn("concurrency:", self.workflow)
        self.assertIn("group: douyin-spark-flow", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_restores_runtime_state_from_artifact(self):
        self.assertNotIn("actions/cache@", self.workflow)
        self.assertIn("python -m utils.artifact_state", self.workflow)
        self.assertIn("restore", self.workflow)
        self.assertIn("RUNTIME_STATE_FILE=", self.workflow)
        self.assertIn("bootstrap_state:", self.workflow)

    def test_uploads_only_encrypted_state_for_ninety_days(self):
        self.assertIn("uses: actions/upload-artifact@v4", self.workflow)
        self.assertIn(
            "name: douyin-runtime-state-${{ github.run_id }}",
            self.workflow,
        )
        self.assertIn("path: .runtime-state/state.enc", self.workflow)
        self.assertIn("retention-days: 90", self.workflow)
        self.assertIn("if: ${{ always()", self.workflow)
        self.assertIn("RUNTIME_STATE_UNCERTAIN_MARKER:", self.workflow)
        self.assertIn(
            "refusing to publish successor artifact",
            self.workflow,
        )

    def test_runtime_permissions_are_read_only(self):
        self.assertIn("permissions:", self.workflow)
        self.assertIn("actions: read", self.workflow)
        self.assertIn("contents: read", self.workflow)

    def test_environment_export_runs_as_a_package_module(self):
        self.assertIn("run: python -m utils.export_github_env", self.workflow)
        self.assertNotIn("run: python utils/export_github_env.py", self.workflow)


if __name__ == "__main__":
    unittest.main()
