#!/usr/bin/env python3
"""Build and smoke-test Tinman's wheel and sdist in isolated environments."""

from pathlib import Path
import subprocess
import sys
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
            "assert importlib.metadata.version('tinman'); "
            "root = importlib.resources.files('tinman'); "
            "assert root.joinpath('templates/account_create.html').is_file(); "
            "assert root.joinpath('static/bootstrap.min.css').is_file()"
        ),
    ], cwd=work_directory)


def main():
    with tempfile.TemporaryDirectory(prefix="tinman-artifacts-") as temporary:
        work_directory = Path(temporary)
        dist_directory = work_directory / "dist"
        run([
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(dist_directory),
            str(PROJECT_ROOT),
        ], cwd=work_directory)

        wheels = sorted(dist_directory.glob("*.whl"))
        sdists = sorted(dist_directory.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError(
                "Expected one wheel and one sdist, found {!r}".format(
                    [path.name for path in dist_directory.iterdir()]
                )
            )
        for artifact in [wheels[0], sdists[0]]:
            smoke_artifact(artifact, work_directory)


if __name__ == "__main__":
    main()
