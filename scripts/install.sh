#!/usr/bin/env bash
set -euo pipefail

LAB_USER=labuser
REPO="https://github.com/kieranhogg/lab-scorer.git"
LABS_REPO="https://github.com/kieranhoggmv/skill-labs.git"
APP_DIR=/opt/lab

main() {
    lab_arg=${1:?usage: curl -sL <raw url> | sudo bash -s -- module-X/unit-X}
    lab_src=$(realpath -m "$lab_arg")
    repo=/opt/lab-scorer
    [ "$EUID" -eq 0 ] || { echo "Run as root" >&2; exit 1; }

    getent passwd "$LAB_USER" >/dev/null || { echo "No such user: $LAB_USER" >&2; exit 1; }
    HOME_DIR=$(getent passwd "$LAB_USER" | cut -d: -f6)
    STUDENT_DIR="$HOME_DIR/lab"

    export PATH=$PATH:/snap/bin
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq git curl ca-certificates

    if ! command -v uv >/dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | UV_UNMANAGED_INSTALL=/usr/local/bin sh
    fi

    if [ -d "$repo/.git" ]; then
        git -C "$repo" pull --ff-only
    else
        git clone --depth 1 "$REPO" "$repo"
    fi
    cd "$repo"

    if [ ! -d "$lab_src" ]; then
        labs_tmp=$(mktemp -d)
        trap 'rm -rf "$labs_tmp"' EXIT
        git clone --depth 1 --filter=blob:none --sparse "$LABS_REPO" "$labs_tmp"
        git -C "$labs_tmp" sparse-checkout set "$lab_arg"
        lab_src=$labs_tmp/$lab_arg
    fi
    [ -d "$lab_src" ] || { echo "No such lab folder: $lab_arg" >&2; exit 1; }

    export UV_PYTHON_INSTALL_DIR=/opt/python
    export UV_TOOL_DIR=/opt/uv-tools
    export UV_TOOL_BIN_DIR=/usr/local/bin
    export LAB_DIR=$repo LAB_HOME=$STUDENT_DIR

    UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-install-project --no-dev
    uv tool install --force .

    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR" "$STUDENT_DIR"
    cp -r "$lab_src"/. "$APP_DIR"/
    if [ -d "$lab_src/files" ]; then
        cp -r "$lab_src/files"/. "$STUDENT_DIR"/
    fi

    /opt/venv/bin/python -c "from labtools.task import setup_lab; setup_lab()"

    chmod -R a+rX "$APP_DIR"
    chown -R "$LAB_USER": "$STUDENT_DIR"

    settings_dir="$HOME_DIR/.config/Code/User"
    runuser -u "$LAB_USER" -- mkdir -p "$settings_dir"
    runuser -u "$LAB_USER" -- tee "$settings_dir/settings.json" >/dev/null <<'JSON'
{
    "workbench.startupEditor": "none",
    "workbench.welcomePage.walkthroughs.openOnInstall": false,
    "chat.disableAIFeatures": true,
    "chat.commandCenter.enabled": false,
    "files.exclude": {
        "**/.lab_step": true,
        "**/.lab_step.tmp": true,
        "**/.student_cwd": true,
        "**/.setup-done": true
    }
}
JSON

    if ! command -v code >/dev/null && command -v snap >/dev/null; then
        snap install code --classic || echo "VS Code install failed, install it by hand" >&2
    fi

    cat > /usr/local/bin/lab <<EOF
#!/usr/bin/env bash
[ "\$EUID" -eq 0 ] || exec sudo "\$0" "\$@"
exec env LAB_DIR=$repo LAB_HOME=$STUDENT_DIR /opt/venv/bin/python $repo/run.py
EOF
    chmod 755 /usr/local/bin/lab
    echo "Installed. Start the lab with: lab"
}

main "$@"