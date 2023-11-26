#!/bin/bash -e -u

PYTHON=python3.11
VENV=.venv

create_venv() {
    if [ ! -d $VENV ]; then
        echo "Creating virtual environment..."
        $PYTHON -m venv $VENV
    fi
}

activate_venv() {
    create_venv

    if [ -z "${VENV_ACTIVATED:-}" ]; then
        echo "Activating virtual environment..."
        source $VENV/bin/activate
    fi

    VENV_ACTIVATED=1
}

install() {
    echo "Installing dependencies..."
    activate_venv
    pip install -e ".[dev]" "$@"
}

"$@"
