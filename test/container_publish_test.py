import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


CONTAINER_JOB = (
    (Path(__file__).resolve().parents[1] / ".gitlab-ci.yml").read_text()
    .split("\ncontainer:\n", 1)[1].split("\nhive-read-only:\n", 1)[0]
)
PUBLISH_SCRIPT = textwrap.dedent(CONTAINER_JOB.split("    - |\n", 1)[1])


class ContainerPublishTest(unittest.TestCase):
    def run_publish(self, branch="master", sha="new", head="new",
                    source="push", lookup_exit=0):
        with tempfile.TemporaryDirectory() as temporary:
            push_log = Path(temporary) / "pushes"
            push_log.touch()
            result = subprocess.run([
                "/bin/sh", "-eu", "-c", """
docker() {
    case "$1" in
        login) cat >/dev/null ;;
        tag) : ;;
        push) printf '%s\\n' "$2" >> "$PUSH_LOG" ;;
        *) return 99 ;;
    esac
}
git() {
    test "$*" = "ls-remote --exit-code origin refs/heads/$CI_COMMIT_BRANCH" || return 99
    if [ "$LOOKUP_EXIT" != 0 ]; then return "$LOOKUP_EXIT"; fi
    printf '%s\\trefs/heads/%s\\n' "$REMOTE_HEAD" "$CI_COMMIT_BRANCH"
}
""" + PUBLISH_SCRIPT,
            ], env=dict(
                os.environ,
                CI_PIPELINE_SOURCE=source, CI_COMMIT_BRANCH=branch,
                CI_COMMIT_SHA=sha, CI_REGISTRY_IMAGE="registry/tinman",
                CI_REGISTRY="registry", CI_REGISTRY_USER="test-user",
                CI_REGISTRY_PASSWORD="test-password", TINMAN_IMAGE="tinman:" + sha,
                PUSH_LOG=str(push_log), REMOTE_HEAD=head,
                LOOKUP_EXIT=str(lookup_exit),
            ), capture_output=True, text=True, timeout=10)
            return result, push_log.read_text().splitlines()

    def test_current_head_publishes_commit_and_branch(self):
        for branch in ("develop", "master"):
            with self.subTest(branch=branch):
                result, pushes = self.run_publish(branch=branch)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(pushes, ["registry/tinman:new", "registry/tinman:" + branch])

    def test_old_retry_cannot_replace_newer_branch_tag(self):
        for branch in ("develop", "master"):
            with self.subTest(branch=branch):
                result, pushes = self.run_publish(branch=branch, sha="old", head="new")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(pushes, ["registry/tinman:old"])

    def test_failed_or_missing_head_lookup_does_not_update_branch(self):
        for lookup_exit in (2, 128):
            with self.subTest(lookup_exit=lookup_exit):
                result, pushes = self.run_publish(lookup_exit=lookup_exit)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(pushes, ["registry/tinman:new"])

    def test_only_branch_pushes_publish(self):
        for source, branch in (("merge_request_event", "develop"), ("schedule", "master"),
                               ("web", "master"), ("push", "feature"), ("push", "")):
            with self.subTest(source=source, branch=branch):
                result, pushes = self.run_publish(source=source, branch=branch)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(pushes, [])

    def test_branch_publishers_share_a_resource_group(self):
        self.assertIn("  resource_group: container-$CI_COMMIT_REF_SLUG\n", CONTAINER_JOB)
