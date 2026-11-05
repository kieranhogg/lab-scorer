FROM ubuntu:24.04
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV LAB_DIR=/app LAB_HOME=/lab LC_ALL=C.UTF-8
#ENV LAB_DIR=/app LC_ALL=C.UTF-8
ARG LAB_FILES
ENV LAB_FILES=$LAB_FILES
#ENV LAB_HOME=/opt/lab
WORKDIR /app
COPY pyproject.toml uv.lock ./
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-install-project --no-dev
RUN --mount=target=/var/lib/apt/lists,type=cache,sharing=locked \
    --mount=target=/var/cache/apt,type=cache,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get -y --no-install-recommends install \
        auditd
RUN mkdir -p /etc/audit/rules.d/ && touch /etc/audit/rules.d/lab.rules
RUN echo "-a always,exit -F arch=b64 -S execve -F auid>=1000 -F auid!=-1 -k labcmd" > /etc/audit/rules.d/lab.rules
RUN cat > /etc/profile.d/lab-audit.sh <<'EOF'
[[ $- == *i* ]] || return
trap 'printf "%s\n" "$BASH_COMMAND" >> /var/log/lab-cmds.log' DEBUG
EOF
RUN echo "source /etc/profile.d/lab-audit.sh" >> /etc/bash.bashrc
RUN touch /var/log/lab-cmds.log && chmod 666 /var/log/lab-cmds.log
RUN mkdir /lab
COPY labtools ./labtools
ENV UV_TOOL_DIR=/opt/uv-tools
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --editable .
COPY $LAB_FILES/ /opt/lab/
RUN /opt/venv/bin/python -c "import logging; logging.basicConfig(level=logging.INFO, format='  %(message)s'); from labtools.task import setup_lab; setup_lab()"
COPY run.py ./
COPY $LAB_FILES/fil[e]s/ /lab/
RUN chmod -R a+rX /opt/lab /lab /app/labtools
CMD ["/opt/venv/bin/python", "run.py"]