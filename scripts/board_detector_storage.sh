#!/usr/bin/env bash
# Sourced by setup and runner. The Python helper emits only shlex-quoted exports.
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPYCACHEPREFIX
BOARD3_STORAGE_EXPORTS="$(python3 -B "$ROOT/training/board_detector_storage.py" --project "$ROOT" --shell)" || return $?
eval "$BOARD3_STORAGE_EXPORTS"
unset BOARD3_STORAGE_EXPORTS
