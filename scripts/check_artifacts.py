#!/usr/bin/env python3
"""Build and smoke-test Tinman's wheel and sdist in isolated environments."""

from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command, *, cwd):
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def environment_python(environment):
    directory = "Scripts" if sys.platform == "win32" else "bin"
    executable = "python.exe" if sys.platform == "win32" else "python"
    return environment / directory / executable


def smoke_artifact(artifact, work_directory):
    environment = work_directory / (artifact.name.replace(".", "-") + "-venv")
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment_python(environment)
    run([python, "-m", "pip", "install", str(artifact)], cwd=work_directory)
    run([python, "-m", "tinman", "--help"], cwd=work_directory)
    run([
        python,
        "-c",
        (
            "import importlib.metadata, importlib.resources; "
            "import importlib.util; "
            "assert importlib.metadata.version('tinman'); "
            "assert importlib.util.find_spec('simple_steem_client') is None; "
            "root = importlib.resources.files('tinman'); "
            "assert root.joinpath('templates/account_create.html').is_file(); "
            "assert root.joinpath('static/bootstrap.min.css').is_file()"
        ),
    ], cwd=work_directory)


def check_sdist_contents(sdist):
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
    required_suffixes = (
        "/txgen.conf.example",
        "/server.conf.example",
        "/scripts/hive_compatibility.py",
        "/test/txgen_test.py",
    )
    for suffix in required_suffixes:
        if not any(name.endswith(suffix) for name in names):
            raise RuntimeError("sdist omitted {}".format(suffix[1:]))
    if any("simple_steem_client" in name for name in names):
        raise RuntimeError("sdist contains removed simple_steem_client package")


def main():
    with tempfile.TemporaryDirectory(prefix="tinman-artifacts-") as temporary:
        work_directory = Path(temporary)
        dist_directory = work_directory / "dist"
        source_directory = work_directory / "source"
        shutil.copytree(
            PROJECT_ROOT,
            source_directory,
            ignore=shutil.ignore_patterns(
                ".git", ".tox", ".venv", "build", "dist", "*.egg-info",
                "__pycache__", ".malp", ".clawpatch", ".idea",
            ),
        )
        run([
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(dist_directory),
            str(source_directory),
        ], cwd=work_directory)

        wheels = sorted(dist_directory.glob("*.whl"))
        sdists = sorted(dist_directory.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError(
                "Expected one wheel and one sdist, found {!r}".format(
                    [path.name for path in dist_directory.iterdir()]
                )
            )
        check_sdist_contents(sdists[0])
        for artifact in [wheels[0], sdists[0]]:
            smoke_artifact(artifact, work_directory)


if __name__ == "__main__":
    main()
