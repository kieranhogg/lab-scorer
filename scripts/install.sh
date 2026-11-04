#!/usr/bin/env bash
set -euo pipefail

main() {
    lab_arg=${1:?usage: curl -sL <raw url> | sudo bash -s -- labs/cli}
    lab_src=$(realpath -m "$lab_arg")
    repo=/opt/lab-scorer
    [ "$EUID" -eq 0 ] || { echo "Run as root" >&2; exit 1; }

    export PATH=$PATH:/snap/bin
    if ! command -v uv >/dev/null && ! snap list astral-uv >/dev/null 2>&1; then
        snap install astral-uv --classic
    fi

    command -v git >/dev/null || apt-get install -y git
    if [ -d "$repo/.git" ]; then
        git -C "$repo" pull --ff-only
    else
        git clone --depth 1 https://github.com/kieranhogg/lab-scorer.git "$repo"
    fi
    cd "$repo"
    [ -d "$lab_src" ] || lab_src=$repo/$lab_arg
    [ -d "$lab_src" ] || { echo "No such lab folder: $lab_arg" >&2; exit 1; }

    export UV_PYTHON_INSTALL_DIR=/opt/python
    export UV_TOOL_DIR=/opt/uv-tools
    export UV_TOOL_BIN_DIR=/usr/local/bin
    export LAB_DIR=$repo LAB_HOME=/lab

    UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-install-project --no-dev
    uv tool install --force .

    mkdir -p /opt/lab /lab
    cp -r "$lab_src"/. /opt/lab/
    if [ -d "$lab_src/files" ]; then
        cp -r "$lab_src/files"/. /lab/
    fi

    /opt/venv/bin/python -c "from labtools.task import setup_lab; setup_lab()"
    lab_user=$(/opt/venv/bin/python -c "from labtools.task import get_lab_user; print(get_lab_user() or '')")
    if [ -n "$lab_user" ]; then
        settings_dir=$(getent passwd "$lab_user" | cut -d: -f6)/.config/Code/User
        runuser -u "$lab_user" -- mkdir -p "$settings_dir"
        runuser -u "$lab_user" -- tee "$settings_dir/settings.json" >/dev/null <<'JSON'
{
    "workbench.startupEditor": "none",
    "workbench.welcomePage.walkthroughs.openOnInstall": false,
    "chat.disableAIFeatures": true,
    "chat.commandCenter.enabled": false
}
JSON
    fi
    chmod -R a+rX /opt/lab /lab

    if ! command -v code >/dev/null && command -v snap >/dev/null; then
        snap install code --classic || echo "VS Code install failed, install it by hand" >&2
    fi

    cat > /usr/local/bin/lab <<EOF
#!/usr/bin/env bash
[ "\$EUID" -eq 0 ] || exec sudo "\$0" "\$@"
exec env LAB_DIR=$repo LAB_HOME=/lab /opt/venv/bin/python $repo/run.py
EOF
    chmod 755 /usr/local/bin/lab
    echo "Installed. Start the lab with: lab"
}

main "$@"