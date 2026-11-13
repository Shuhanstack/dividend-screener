#!/usr/bin/env bash
# Keep the SQLite database on a `data` branch so it survives between runs.
#
#   scripts/data-branch.sh restore [db_path]   # fetch branch -> db (no-op if branch missing)
#   scripts/data-branch.sh save    [db_path]   # db -> single-commit branch, force-pushed
#
# The branch always holds exactly one commit (gzipped DB + README), so the
# repository does not grow week over week. It uses the checkout's existing git
# credentials (in GitHub Actions: the workflow's GITHUB_TOKEN).
set -euo pipefail

cmd=${1:?usage: data-branch.sh restore|save [db_path]}
db=${2:-backend/data/screener.db}
branch=${DATA_BRANCH:-data}
remote=${DATA_REMOTE:-origin}

case "$cmd" in
  restore)
    if git fetch --quiet --depth=1 "$remote" "refs/heads/$branch" 2>/dev/null; then
      mkdir -p "$(dirname "$db")"
      git show FETCH_HEAD:screener.db.gz | gunzip > "$db.tmp"
      mv "$db.tmp" "$db"
      echo "Restored database ($(wc -c < "$db" | awk '{printf "%.1f MB", $1/1048576}')) from '$branch' branch, saved $(git log -1 --format=%cI FETCH_HEAD)."
    else
      echo "No '$branch' branch yet; starting from an empty database."
    fi
    ;;
  save)
    if [ ! -s "$db" ]; then
      echo "No database at $db; nothing to save."
      exit 0
    fi
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    gzip -9 -c "$db" > "$tmp/screener.db.gz"
    cat > "$tmp/README.md" <<'MD'
# data branch

Machine-written by the weekly workflow: the screener's SQLite database
(`screener.db.gz`), kept so that stocks which fail to download in a given
week keep their previous data. Force-pushed each run (single commit).
Not financial data you should rely on; see the main README.
MD
    blob_db=$(git hash-object -w "$tmp/screener.db.gz")
    blob_md=$(git hash-object -w "$tmp/README.md")
    tree=$(printf '100644 blob %s\tREADME.md\n100644 blob %s\tscreener.db.gz\n' "$blob_md" "$blob_db" | git mktree)
    export GIT_AUTHOR_NAME=${GIT_AUTHOR_NAME:-github-actions[bot]}
    export GIT_AUTHOR_EMAIL=${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}
    export GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL
    commit=$(git commit-tree "$tree" -m "Database snapshot $(date -u +%Y-%m-%dT%H:%MZ)")
    git push --quiet --force "$remote" "$commit:refs/heads/$branch"
    echo "Saved database ($(wc -c < "$tmp/screener.db.gz" | awk '{printf "%.1f MB", $1/1048576}') gzipped) to '$branch' branch."
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
