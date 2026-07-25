#!/usr/bin/env bash
# Offline unit tests. PYTEST_DISABLE_PLUGIN_AUTOLOAD stops ROS Jazzy's pytest
# entrypoint (on PYTHONPATH) from crashing collection.
set -e
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest "$@"
