import argparse
import json
import subprocess
from pathlib import Path


PREFIX = "douyin-runtime-state-"


class StateContinuityError(RuntimeError):
    pass


def artifact_run_id(artifact):
    name = artifact.get("name", "")
    suffix = name.removeprefix(PREFIX)
    if not suffix.isdigit():
        raise ValueError("Invalid runtime-state artifact name")
    return int(suffix)


def select_runtime_artifact(
    artifacts,
    workflow_runs,
    current_run_id,
    allow_bootstrap,
):
    if allow_bootstrap:
        return None
    candidates = [
        artifact
        for artifact in artifacts
        if artifact.get("name", "").startswith(PREFIX)
        and not artifact.get("expired", False)
        and artifact_run_id(artifact) < current_run_id
    ]
    if not candidates:
        raise StateContinuityError(
            "No encrypted runtime-state artifact; run validation bootstrap"
        )
    latest = max(candidates, key=lambda item: item["created_at"])
    latest_run_id = artifact_run_id(latest)
    gaps = [
        run
        for run in workflow_runs
        if latest_run_id < run.get("id", 0) < current_run_id
        and run.get("status") == "completed"
        and run.get("event") in {"schedule", "workflow_dispatch"}
    ]
    if gaps:
        raise StateContinuityError(
            "A newer workflow run has no runtime-state artifact"
        )
    return latest


def gh_json(endpoint):
    completed = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def restore(repository, workflow_id, current_run_id, output, allow_bootstrap):
    artifacts_response = gh_json(
        f"repos/{repository}/actions/artifacts?per_page=100"
    )
    runs_response = gh_json(
        f"repos/{repository}/actions/workflows/{workflow_id}/runs?per_page=100"
    )
    artifact = select_runtime_artifact(
        artifacts_response.get("artifacts", []),
        runs_response.get("workflow_runs", []),
        current_run_id,
        allow_bootstrap,
    )
    if artifact is None:
        return False
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(artifact_run_id(artifact)),
            "--repo",
            repository,
            "--name",
            artifact["name"],
            "--dir",
            str(destination.parent),
        ],
        check=True,
    )
    downloaded = destination.parent / "state.enc"
    if downloaded != destination:
        downloaded.replace(destination)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices={"restore"})
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-bootstrap", action="store_true")
    args = parser.parse_args()
    restored = restore(
        args.repository,
        args.workflow,
        args.run_id,
        args.output,
        args.allow_bootstrap,
    )
    if restored:
        print("Encrypted runtime state restored")
    else:
        print("Runtime-state bootstrap requested")


if __name__ == "__main__":
    main()
