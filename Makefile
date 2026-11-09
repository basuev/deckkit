PYTHON ?= python3
RUFF ?= .venv/bin/ruff
REPOSITORY ?= basuev/deckkit
DOCKER ?= docker
SCREEN ?= catalog
PREVIEW_ARGS ?=

.PHONY: dev check test test-ui preview preview-container release

dev:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'

check:
	$(RUFF) check src/deckkit tests scripts
	$(RUFF) format --check src/deckkit tests scripts

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

preview:
	PYTHONPATH=src:tests $(PYTHON) scripts/preview.py $(SCREEN) $(PREVIEW_ARGS)

preview-container:
	DOCKER="$(DOCKER)" scripts/preview-container.sh $(SCREEN) $(PREVIEW_ARGS)

test-ui:
	$(DOCKER) build -t deckkit-builder:local -f scripts/Dockerfile .
	$(DOCKER) run --rm --init --user "$$(id -u):$$(id -g)" \
		-e PYTHONPATH=src --entrypoint /usr/bin/xvfb-run \
		-v "$(CURDIR):/work" deckkit-builder:local -a \
		/usr/bin/python3 -m unittest discover -s tests -v

release:
	$(DOCKER) build -t deckkit-builder:local -f scripts/Dockerfile .
	$(DOCKER) run --rm --user "$$(id -u):$$(id -g)" \
		-e XDG_CACHE_HOME=/tmp/deckkit-cache \
		-v "$(CURDIR):/work" deckkit-builder:local \
		scripts/build_release.py --repository "$(REPOSITORY)"
