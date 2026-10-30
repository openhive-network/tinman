# The image AIDEV runs this project's suites in (`environment.image` in
# .aidev/project.yaml). AIDEV runs it as `docker run --rm --network none --user
# <uid>:<gid> -v <workspace>:/work`, so everything a suite needs is in the image.
#
# Based on python:3.12, the image of CI's package job (and one leg of the
# python/server matrix), pinned by digest. It adds
#   - the runtime and `server` extra dependencies of pyproject.toml, installed;
#   - a wheelhouse (/opt/wheels) holding what scripts/check_artifacts.py's
#     isolated builds and smoke venvs install, so pip resolves offline from it.
#
# .aidev/runtime/build.sh builds it; the result is pinned as `environment.image`.
# See .aidev/README.md.
ARG BASE_IMAGE=python:3.12@sha256:17b9724493d916f56565c131f389faff2597f46dec6ce09516f95125bc9f519f
FROM ${BASE_IMAGE}
ENV HOME=/tmp \
    PIP_NO_INDEX=1 \
    PIP_FIND_LINKS=/opt/wheels \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN PIP_NO_INDEX= PIP_FIND_LINKS= python -m pip download --no-cache-dir -d /opt/wheels \
        "setuptools>=68" wheel "build>=1.2" "ijson>=3.4,<4" "Flask>=3.1,<4" "WTForms>=3.2,<4" pip \
    && python -m pip install --no-cache-dir "build>=1.2" "ijson>=3.4,<4" "Flask>=3.1,<4" "WTForms>=3.2,<4" \
    && chmod -R a+rX /opt/wheels && rm -rf /tmp/.cache
