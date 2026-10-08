.DEFAULT_GOAL := help
SHELL := /bin/bash
.PHONY: help install lint unit integration test build artifact-check browser-install e2e vuln check dev stop clean
help:
	@printf '%s\n' 'make install: pinned tools and dependencies' 'make lint / unit / integration: separate verification layers' 'make test: unit + integration' 'make check: all applicable checks'
test: unit integration
build artifact-check browser-install e2e vuln dev stop:
	@echo '$@: inapplicable: composite action library; no application, browser or shipping image'
check: lint test
clean:
	rm -rf .artifacts

install:
	@command -v bash >/dev/null && command -v python3 >/dev/null
lint:
	bash -n tests/test-contracts.sh
	python3 -c 'import ast; from pathlib import Path; [ast.parse(Path(p).read_text()) for p in ("release/release.py", "publish/publish.py")]'
unit:
	bash tests/test-contracts.sh
	python3 -m unittest discover -s tests -p 'test_publish.py' -v
	python3 -m unittest discover -s tests -p 'test_release.py' -v
integration:
	python3 -m unittest discover -s tests -p 'test_installer.py' -v
