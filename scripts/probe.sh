#!/usr/bin/env bash
log=/var/log/lab-cmds.log
: > "$log"
bash -ic ':' >/dev/null 2>&1 </dev/null
startup=$(( $(wc -l < "$log") - 1 ))
: > "$log"
bash -ic "$1" >/dev/null 2>&1 </dev/null
tail -n +"$(( startup + 1 ))" "$log"