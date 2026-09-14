#!/bin/bash

# Verifier entrypoint. Runs in the verifier container, not the agent's: it sees only the paths
# declared in `artifacts`. All tooling is baked into tests/Dockerfile; nothing is fetched here.

set -uo pipefail

mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt

# Fold stderr into stdout: only stdout survives into the feedback bundle.
exec 2>&1

as_runner() {
  setpriv --clear-groups --no-new-privs --reuid runner --regid runner "$@"
}

# The shipped tests/ directory lands here at runtime, so the verifier's own code sits under
# /tests just as agent-authored code is about to run. Close it to the build user first: root still
# reads it, `runner` cannot traverse it. If it is still reachable the run is abandoned with reward
# 0 rather than graded. `test -r` on a file is not enough on its own: access(2) answers true for a
# chmod 700 directory the user cannot actually read, so a listing of the key directory is tried too.
chmod 700 /tests 2>/dev/null || true
chmod 700 /logs/verifier 2>/dev/null || true
if as_runner bash -c 'test -r /tests/test_outputs.py || ls /opt/golden || ls /opt/hidden' >/dev/null 2>&1; then
  echo "FATAL: /tests or the answer keys are still reachable by the unprivileged build user;"
  echo "the verifier's code and keys are exposed to agent-authored code, so this run cannot be graded."
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi
echo "verifier files closed to the unprivileged build user"

# The shipped export is checked back against its hashes by pytest, so it stays where it landed,
# read-only. A root-owned pristine copy of the agent's project is kept so each build starts from
# exactly what was collected; cp -a keeps the agent's file modes, so write bits are stripped.
chmod -R a-w /app/data
cp -a /app/screen /opt/screen_pristine
chmod -R go-w /opt/screen_pristine

# The task states the tool is TypeScript run under node and that nothing else on the box is
# executable while it runs. This image ships a Python interpreter because pytest scores the result
# with it, the compiler because the tool has to be built, and the usual coreutils. Every executable
# on the system paths except node itself is closed to the build user for the seconds the program
# runs, found by walking the directories rather than by a list, so the graded list cannot come out
# of a python, awk, cut or cat the program spawns, and reopened straight after. Root is unaffected.
TOOLS="$( { find /usr/local/bin /usr/local/sbin /usr/bin /bin /usr/sbin /sbin -xdev -type f -perm /111 2>/dev/null;
             for l in $(find /usr/local/bin /usr/bin /bin -xdev -type l 2>/dev/null); do t="$(readlink -f "$l")"; [ -f "$t" ] && echo "$t"; done; } \
  | sort -u | grep -v -E 'ld-linux|/ld\.so$' | grep -v -E '/(node|nodejs)$' | grep -v -x -F -e "$(readlink -f /usr/bin/node)")"
# Nothing but node is left open. Each run is started by a root shell that changes directory itself
# and then execs node, so /usr/bin/env is not needed as a launcher and is closed with the rest.
# Only regular files are listed: the
# merged /bin is itself a symlink to /usr/bin, and closing that directory would shut the whole
# tree, launcher included. The dynamic loader is left out as well: /usr/bin/ld.so links to it, and
# closing it would stop every dynamically linked program, node included, not only the ones the
# agent's code might spawn.
close_tools() { for f in $TOOLS; do chmod 750 "$f" 2>/dev/null || true; done; }
open_tools()  { for f in $TOOLS; do chmod 755 "$f" 2>/dev/null || true; done; }
trap open_tools EXIT

# Compile the collected source ourselves, as the build user, from the directory the instruction
# documents, with our own compiler settings rather than anything the project ships. Whatever dist/
# the agent left behind is discarded first, so what runs is always a fresh compile of the one file
# the contract names.
rm -rf /app/screen
cp -a /opt/screen_pristine /app/screen
rm -rf /app/screen/dist
# The contract says the program is the one file and that imports stop at node's own modules.
# Both are settled here rather than by reading the source: everything else under src goes before
# the compiler runs, so a library vendored beside screen.ts is not there to import, and neither
# is a package. The tsconfig is ours, not the collected one.
# Depth one and rm -rf, not -delete: -delete on a non-empty directory fails quietly and would
# leave a second source alive at src/<dir>/screen.ts, which the graded tsconfig's src/**/*.ts
# would then compile.
find /app/screen/src -mindepth 1 -maxdepth 1 ! -name screen.ts -exec rm -rf {} + 2>/dev/null || true
rm -rf /app/screen/node_modules /app/screen/package.json
chown -R runner:runner /app/screen /app/out
install -m 444 -o root -g root /tests/graded_tsconfig.json /app/screen/tsconfig.json
( cd /app/screen && exec setsid \
    setpriv --clear-groups --no-new-privs --reuid runner --regid runner \
    /usr/local/bin/tsc -p /app/screen ) &
bpid=$!
wait "$bpid"
bstatus=$?
echo "build exit status: $bstatus"
# setsid makes the child a session leader, so its group id is its own pid and can be addressed
# directly. Reading it out of /proc races setsid and has taken down the verifier on sibling tasks.
kill -TERM -- -"$bpid" 2>/dev/null || true
kill -KILL -- -"$bpid" 2>/dev/null || true
as_runner bash -c 'kill -9 -1' 2>/dev/null || true
[ "$bstatus" -eq 0 ] && [ -f /app/screen/dist/screen.js ] || echo "the collected sources did not compile into /app/screen/dist/screen.js"
# A compile that reported errors is not a build we grade, even if tsc still emitted something.
if [ "$bstatus" -ne 0 ]; then rm -f /app/screen/dist/screen.js; fi
# What the compiler produced becomes root's from here on. The build user still reads and runs it,
# but cannot rewrite it, so the first run cannot leave a different program behind for the second.
chown -R root:root /app/screen/dist 2>/dev/null || true
chmod -R go-w /app/screen/dist 2>/dev/null || true

# The single-file rule was enforced under src only, and src is not the only place the agent can
# leave code: /app/data and /app/out are declared artifacts as well. The export is the five
# checked files, and once the sweep below has run they are the only things there at all.
# README.md is documentation about the export for whoever is reading it; the
# reference never opens it and nothing in the contract asks the program to, so it is not one of
# the five and it goes here with anything else parked in the directory. Left in place it would be
# a second, unhashed file the compiled program could read at run time, which is exactly the kind
# of program logic the single-file rule exists to keep out of anywhere but screen.ts. Everything
# in the project that is not the compiled program becomes root's and unreadable, so a module left
# beside it cannot be required either. And the compiler's own package tree is closed for the runs,
# since an absolute import would otherwise reach it.
# Anything that is not a regular file goes first, symlinks included: the copy below runs as root,
# and a link planted here pointing into /opt would otherwise be dereferenced into the directory
# the program is handed. Depth one and rm -rf, so a directory goes whole.
find /app/data -mindepth 1 -maxdepth 1 ! -type f -exec rm -rf {} + 2>/dev/null || true
find /app/data -mindepth 1 -type f \
  ! -name results.csv ! -name reference_materials.csv ! -name samples.csv \
  ! -name split_checks.csv ! -name policy.json -delete
chown -R root:root /app/screen
find /app/screen -type d -exec chmod 755 {} +
find /app/screen -type f ! -path '/app/screen/dist/*' -exec chmod 600 {} +
chmod -R a+rX /app/screen/dist
TSLIB="$(dirname "$(readlink -f /usr/local/bin/tsc)")/.."
close_pkgs() { chmod -R go-rX /usr/local/lib/node_modules "$TSLIB" 2>/dev/null || true; }
open_pkgs()  { chmod -R go+rX /usr/local/lib/node_modules "$TSLIB" 2>/dev/null || true; }

# run_once <data-dir> <asked-for-path> <capture-path>: run the compiled program on an export, as
# the build user, with every tool but node closed, from /app/screen, and move what it wrote to a
# root-only path. The two runs ask for different destinations, so a program that ignores its second
# argument and writes to a fixed name of its own fails the second run rather than passing unnoticed.
# Only a regular file is ever staged: the program cannot read the keys, but it can drop a symlink
# at the output path pointing into /opt, and pytest, running as root, would then read the
# verifier's own truth back as the agent's list.
run_once() {
  local data="$1" asked="$2" out="$3" pid
  # /app/out is collected from the agent's box, so whatever it left there is swept before each
  # run. Otherwise a thin screen.ts could require a module sitting beside its own output.
  rm -rf /app/out
  mkdir -p /app/out
  chown runner:runner /app/out
  rm -f "$asked"
  # Nothing inside the project may execute except the script node was handed. The tool closure
  # above covers the system paths, which leaves an executable the agent shipped in its own project
  # still runnable; the graded figures have to come out of the compiled TypeScript.
  find /app/screen -type f -perm /111 -exec chmod a-x {} + 2>/dev/null || true
  close_tools
  close_pkgs
  # The root shell changes directory before dropping privileges, so setpriv execs node itself and
  # nothing else needs to stay open to the build user.
  ( cd /app/screen && HOME=/home/runner exec setsid \
      setpriv --clear-groups --no-new-privs --reuid runner --regid runner \
      /usr/bin/node /app/screen/dist/screen.js "$data" "$asked" ) &
  pid=$!
  wait "$pid"
  echo "run exit status: $? ($data -> $asked)"
  open_tools
  open_pkgs
  kill -TERM -- -"$pid" 2>/dev/null || true
  kill -KILL -- -"$pid" 2>/dev/null || true
  as_runner bash -c 'kill -9 -1' 2>/dev/null || true
  if [ -L "$asked" ] || [ ! -f "$asked" ]; then
    echo "no regular file was produced at $asked for $data (absent, or not a regular file)"
    rm -f "$asked"
  else
    mv "$asked" "$out"
    chown root:root "$out" 2>/dev/null || true
    chmod 600 "$out" 2>/dev/null || true
  fi
}


# The shipped export is staged the same way the second one is. Handing it to the program at a
# fixed /app/data would let a program tell the two surveys apart by pathname and pick the limit
# from that rather than from the policy it was given. README.md does not travel here: it was
# already swept out of /app/data above, and it is left out of this copy too so the directory the
# program is handed never carries it, regardless of what order these steps run in.
shipped="$(mktemp -d /app/survey_XXXXXXXX)"
cp -P /app/data/*.csv /app/data/policy.json "$shipped"/
chown -R runner:runner "$shipped"
chmod -R a-w "$shipped"
echo "=== the export that shipped in the agent's image ==="
run_once "$shipped" /app/out/over_limit.json /opt/run_shipped.json
rm -rf "$shipped"

# Then the other survey. Its export is staged only now, after the build and the first run and
# every process they started are gone, into a fresh directory the program has never seen, and
# removed afterwards. Its README.md is left out of this copy too, for the same reason as the
# shipped one: the program is never asked to read it, so it is never handed one.
staged="$(mktemp -d /app/export_XXXXXXXX)"
cp -P /opt/hidden/data/*.csv /opt/hidden/data/policy.json "$staged"/
chown -R runner:runner "$staged"
chmod -R a-w "$staged"
echo "=== the same program on the other survey's export ==="
run_once "$staged" /app/out/second_survey.json /opt/run_hidden.json
rm -rf "$staged"

# Nothing the agent started may be alive while pytest runs or while the reward is written.
as_runner bash -c 'kill -9 -1' 2>/dev/null || true

# -P keeps the working directory off sys.path, so a pytest.py dropped into /app by the program
# cannot shadow the suite. The interpreter is called by full path, not through PATH.
cd /tests
/usr/local/bin/python3 -P -m pytest -o cache_dir=/tmp/pytest_cache \
  --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
exit_code=$?
if [ "$exit_code" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

# Harbor grades from reward.txt, never from this script's exit status.
exit 0
