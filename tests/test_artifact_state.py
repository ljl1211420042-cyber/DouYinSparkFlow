import unittest

from utils.artifact_state import (
    StateContinuityError,
    select_runtime_artifact,
)


class ArtifactStateTests(unittest.TestCase):
    def test_selects_newest_unexpired_runtime_artifact(self):
        artifacts = [
            {
                "id": 10,
                "name": "douyin-runtime-state-100",
                "expired": False,
                "created_at": "2026-07-22T00:00:00Z",
            },
            {
                "id": 11,
                "name": "douyin-runtime-state-101",
                "expired": False,
                "created_at": "2026-07-23T00:00:00Z",
            },
        ]
        artifact = select_runtime_artifact(
            artifacts,
            workflow_runs=[],
            current_run_id=102,
            allow_bootstrap=False,
        )
        self.assertEqual(artifact["id"], 11)

    def test_rejects_completed_run_newer_than_latest_state(self):
        artifacts = [
            {
                "id": 11,
                "name": "douyin-runtime-state-101",
                "expired": False,
                "created_at": "2026-07-23T00:00:00Z",
            }
        ]
        runs = [
            {
                "id": 102,
                "status": "completed",
                "event": "schedule",
                "conclusion": "cancelled",
            }
        ]
        with self.assertRaises(StateContinuityError):
            select_runtime_artifact(
                artifacts,
                workflow_runs=runs,
                current_run_id=103,
                allow_bootstrap=False,
            )

    def test_allows_explicit_first_bootstrap_without_artifact(self):
        self.assertIsNone(
            select_runtime_artifact(
                [],
                workflow_runs=[{"id": 90, "status": "completed"}],
                current_run_id=100,
                allow_bootstrap=True,
            )
        )

    def test_explicit_bootstrap_ignores_old_encrypted_artifact(self):
        self.assertIsNone(
            select_runtime_artifact(
                [
                    {
                        "id": 11,
                        "name": "douyin-runtime-state-101",
                        "expired": False,
                        "created_at": "2026-07-23T00:00:00Z",
                    }
                ],
                workflow_runs=[],
                current_run_id=102,
                allow_bootstrap=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
