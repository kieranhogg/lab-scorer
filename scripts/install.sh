#!/usr/bin/env bash
set -euo pipefail

sudo snap install astral-uv
lab_files=${1:?usage: sudo env PATH="$PATH" scripts/install.sh labs/cli}
repo=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo"

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
    "workbench.welcomePage.walkthroughs.openOnInstall": false
}
EOF
fi
chmod -R a+rX /opt/lab /lab

command -v code >/dev/null || ! command -v snap >/dev/null || snap install code --classic