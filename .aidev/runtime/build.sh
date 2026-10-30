#!/usr/bin/env bash
# Build (and with --push, publish) the test runtime image of .aidev/runtime/Dockerfile
# and print the digest-pinned reference to put in .aidev/project.yaml's
# `environment.image`. See .aidev/README.md.
#
# The tag is `aidev-<hash>` of the image inputs: the Dockerfile (which pins its
# base by digest and names the dependencies it installs) and pyproject.toml
# (`environment.inputs` in .aidev/project.yaml). When
# <repository>:aidev-<hash> is already in the registry nothing is built: the
# script prints its digest.
#
#   .aidev/runtime/build.sh           # registry digest, or build locally and print the local tag
#   .aidev/runtime/build.sh --push    # registry digest, or build + push and print repo@sha256:<digest>
#   .aidev/runtime/build.sh --tag     # print the input-hash tag only
set -euo pipefail
cd "$(dirname "$0")/../.."
REPOSITORY="${AIDEV_RUNTIME_REPOSITORY:-registry.gitlab.syncad.com/hive/tinman/aidev-tests}"
# HASHED decide the tag; the Dockerfile copies nothing from the repository.
HASHED=(pyproject.toml)

input_hash() {
    # BASE_IMAGE is pinned by digest in the Dockerfile, so the Dockerfile's own
    # hash already covers it.
    sha256sum .aidev/runtime/Dockerfile "${HASHED[@]}" | sha256sum | cut -c1-16
}
TAG="aidev-$(input_hash)"
case "${1:-}" in
    --tag) echo "$TAG"; exit 0 ;;
    ""|--push) ;;
    *) echo "usage: $0 [--push|--tag]" >&2; exit 2 ;;
esac

registry_digest() {
    docker buildx imagetools inspect "$REPOSITORY:$TAG" --format '{{json .Manifest}}' 2>/dev/null \
        | grep -o '"digest": *"sha256:[0-9a-f]*"' | head -1 | grep -o 'sha256:[0-9a-f]*' || true
}

# Build through the region's GitLab image cache (:5001): FROM registry.gitlab.syncad.com/... stays
# canonical and BuildKit fetches its blobs from the cache. AIDEV_IMAGE_CACHE_BY_REGION
# (region=host:port,...; a region matches a label of the host's FQDN, * any other host)
# names the caches; unset, the build goes straight to the registry.
region_build() {
  local cache_map="${AIDEV_IMAGE_CACHE_BY_REGION:-}"
  local region="*" label entry cache="" builder config
  local -a entries
  if [ -z "$cache_map" ]; then
    docker build "$@"
    return
  fi
  IFS=, read -r -a entries <<<"$cache_map"
  for label in $( (hostname -f 2>/dev/null || hostname) | tr 'A-Z.' 'a-z '); do
    for entry in "${entries[@]}"; do
      if [ "${entry%%=*}" = "$label" ]; then region="$label"; fi
    done
  done
  for entry in "${entries[@]}"; do
    if [ "${entry%%=*}" = "$region" ]; then cache="${entry#*=}"; fi
  done
  if [ -z "$cache" ]; then
    echo "region_build: no image cache serves region $region; building straight from registry.gitlab.syncad.com" >&2
    docker build "$@"
    return
  fi
  builder="aidev-region-build-${cache//[.:]/-}"
  if ! docker buildx inspect "$builder" >/dev/null 2>&1; then
    config="$(mktemp)"
    printf '[registry."%s"]\n  mirrors = ["%s"]\n\n[registry."%s"]\n  http = true\n  insecure = true\n' \
      "registry.gitlab.syncad.com" "$cache" "$cache" >"$config"
    docker buildx create --name "$builder" --driver docker-container --config "$config" >/dev/null
    rm -f "$config"
  fi
  docker buildx build --builder "$builder" --load "$@"
}

# Push <image>:<tag>, print <image>@sha256:<digest>, and seed the build region's cache
# with that digest (aidev image seed-region-cache) so the region's first pull is a LAN hit.
region_push() {
  local ref
  docker push -q "$1" >/dev/null
  ref="$(docker image inspect "$1" | grep -o "\"${1%:*}@sha256:[0-9a-f]*\"" | head -1 | tr -d '"' || true)"
  if [ -z "$ref" ]; then
    echo "region_push: docker recorded no digest for $1 after the push" >&2
    return 1
  fi
  if [ -n "${AIDEV_IMAGE_CACHE_BY_REGION:-}" ] && [ -z "${AIDEV_RUNTIME_SEED_BY_CALLER:-}" ] && command -v aidev >/dev/null 2>&1; then
    aidev image seed-region-cache "$ref" >&2 || echo "region_push: could not seed the region cache with $ref; the region fetches it from the registry" >&2
  fi
  echo "$ref"
}

digest="$(registry_digest)"
if [ -n "$digest" ]; then
    echo "$REPOSITORY:$TAG exists in the registry; not building" >&2
    echo "$REPOSITORY@$digest"
    exit 0
fi
echo "$REPOSITORY:$TAG is not in the registry; building it" >&2

# The Dockerfile copies nothing: an empty build context.
context="$(mktemp -d)"
trap 'rm -rf "$context"' EXIT
region_build --pull -f .aidev/runtime/Dockerfile -t "$REPOSITORY:$TAG" "$context" >&2
if [ "${1:-}" != "--push" ]; then
    echo "$REPOSITORY:$TAG"
    exit 0
fi
region_push "$REPOSITORY:$TAG"
