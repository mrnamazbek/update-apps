PYTHON ?= python3
BIN_DIR ?= $(HOME)/.local/bin

.PHONY: test install-local

test:
	$(PYTHON) -m unittest discover -v

install-local:
	install -d "$(BIN_DIR)"
	install -m 755 update_apps.py "$(BIN_DIR)/update-apps"
