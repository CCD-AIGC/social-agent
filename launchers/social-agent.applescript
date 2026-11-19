on run
    set homeDir to POSIX path of (path to home folder)
    set projectDir to homeDir & "Projects/social-agent"
    set portValue to "8798"
    set logDir to projectDir & "/logs"
    set commandText to "export PATH=\"$HOME/.local/bin:/opt/homebrew/bin:/opt/local/bin:/usr/local/bin:/usr/bin:/bin\"; PROJECT=" & quoted form of projectDir & "; LOGDIR=" & quoted form of logDir & "; PORT=" & portValue & "; mkdir -p \"$LOGDIR\"; if ! /usr/sbin/lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then (cd \"$PROJECT\" && nohup .venv/bin/social-agent-web --host 127.0.0.1 --port $PORT >> \"$LOGDIR/web.log\" 2>&1 &); fi; i=0; while [ $i -lt 40 ]; do if /usr/bin/curl -fsS http://127.0.0.1:$PORT/api/health >/dev/null 2>&1; then break; fi; /bin/sleep 0.25; i=$((i + 1)); done; /usr/bin/open http://127.0.0.1:$PORT"
    do shell script commandText
end run
