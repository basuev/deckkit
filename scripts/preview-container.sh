#!/bin/sh
set -eu

DECKKIT_STAGE=$(mktemp -d "${TMPDIR:-/tmp}/deckkit-preview.XXXXXX")
trap 'rm -rf "$DECKKIT_STAGE"' EXIT HUP INT TERM

touch "$DECKKIT_STAGE/Xauthority"
# The container has a different hostname. Match the same cookie by any family.
xauth nlist "${DISPLAY:?}" \
    | sed 's/^..../ffff/' \
    | xauth -f "$DECKKIT_STAGE/Xauthority" nmerge -

${DOCKER:-docker} run --rm --init --network none \
    --user "$(id -u):$(id -g)" \
    -e DISPLAY -e XAUTHORITY=/tmp/deckkit.xauth -e PYTHONPATH=src:tests \
    -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
    -v "$DECKKIT_STAGE/Xauthority:/tmp/deckkit.xauth:ro" \
    -v "$PWD:/work:ro" --entrypoint /usr/bin/python3 \
    deckkit-builder:local scripts/preview.py "$@"
