#!/usr/bin/env bash
set -euo pipefail

sudo snap install astral-uv
lab_files=${1:?usage: curl -sL <raw url> | sudo bash -s -- labs/cli}
    repo=/opt/lab-scorer
    [ "$EUID" -eq 0 ] || { echo "Run as root" >&2; exit 1; }

    command -v git >/dev/null || apt-get install -y git
    if [ -d "$repo/.git" ]; then
        git -C "$repo" pull --ff-only
    else
        git clone --depth 1 https://github.com/kieranhogg/lab-scorer.git "$repo"
    fi
    cd "$repo"
    [ -d "$repo/$lab_files" ] || { echo "No such lab folder: $lab_files" >&2; exit 1; }

export UV_PYTHON_INSTALL_DIR=/opt/python
export UV_TOOL_DIR=/opt/uv-tools
export UV_TOOL_BIN_DIR=/usr/local/bin
export LAB_DIR=$repo LAB_HOME=/lab

UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-install-project --no-dev
uv tool install --force .

mkdir -p /opt/lab /lab
cp -r "$lab_files"/. /opt/lab/
[ -d "$lab_files/files" ] && cp -r "$lab_files/files"/. /lab/

/opt/venv/bin/python -c "from labtools.task import setup_lab; setup_lab()"
lab_user=$(/opt/venv/bin/python -c "from labtools.task import get_lab_user; print(get_lab_user() or '')")
if [ -n "$lab_user" ]; then
    settings_dir=$(getent passwd "$lab_user" | cut -d: -f6)/.config/Code/User
    runuser -u "$lab_user" -- mkdir -p "$settings_dir"
    runuser -u "$lab_user" -- tee "$settings_dir/settings.json" >/dev/null <<'EOF'
{
    "workbench.startupEditor": "none",
    "workbench.welcomePage.walkthroughs.openOnInstall": false,
    "chat.disableAIFeatures": true,
    "chat.commandCenter.enabled": false
}
EOF
fi
chmod -R a+rX /opt/lab /lab

command -v code >/dev/null || ! command -v snap >/dev/null || snap install code --classic

cat > /usr/local/bin/lab <<EOF
#!/usr/bin/env bash
[ "\$EUID" -eq 0 ] || exec sudo "\$0" "\$@"
exec env LAB_DIR=$repo LAB_HOME=/lab /opt/venv/bin/python $repo/run.py
EOF
chmod 755 /usr/local/bin/lab