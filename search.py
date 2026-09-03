#!/usr/bin/env python3
r"""
SearchPro — Standalone local search for opencode user prompts

Queries the opencode SQLite DB directly (read-only, WAL-safe).
DB location: --db flag, else $OPENCODE_DB, else ~/.local/share/opencode/opencode.db
Shows project (working folder) + session title + snippet for each matching user prompt.

Usage:
  python search.py "lunch"
  python search.py --all          # list recent prompts
  python search.py --project lunch-portal
  python search.py "revolut" --limit 20

Output columns: Time | Project | Session Title | Snippet | SessionID
Copy SessionID -> in opencode press Ctrl+X L (session list) and paste it.
"""
import sqlite3, json, sys, os, argparse, textwrap, pathlib, datetime

def resolve_db(cli_arg=None):
    import os
    if cli_arg:
        return cli_arg
    env = os.environ.get("OPENCODE_DB")
    if env:
        return env
    return str(pathlib.Path.home() / ".local" / "share" / "opencode" / "opencode.db")

DB = resolve_db()

def open_db():
    # WAL-aware read-only: sees the latest committed frames without blocking the writer.
    # Do NOT use immutable=1 here — it pins reads to the last checkpoint and hides fresh WAL content.
    uri = pathlib.Path(DB).as_uri() + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except:
        # fallback: copy db+wal+shm to temp and read the copy (full state, incl. WAL)
        import shutil, tempfile
        tmp = os.path.join(tempfile.gettempdir(), "opencode_search.db")
        try:
            for suffix in ("", "-wal", "-shm"):
                src = DB + suffix
                if os.path.exists(src):
                    shutil.copy2(src, tmp + suffix)
            con = sqlite3.connect(tmp, timeout=5)
        except Exception as e:
            print(f"Failed to open DB: {e}")
            sys.exit(1)
    con.row_factory = sqlite3.Row
    return con

def normalize(text, max_len=140):
    t = " ".join(text.split())
    return (t[:max_len] + "…") if len(t) > max_len else t

def query_prompts(con, q=None, limit=50, project_filter=None):
    cur = con.cursor()
    # Join session -> project to get working folder, and also fetch prompt text
    # part.data JSON {type:"text", text:"..."} ; message.data JSON {role:"user"}
    sql = """
    SELECT
        s.id as session_id,
        s.title as session_title,
        s.directory as session_dir,
        s.time_updated as time_updated,
        s.time_created as time_created,
        p.worktree as project_worktree,
        p.name as project_name,
        json_extract(m.data, '$.time.created') as msg_time,
        json_extract(pt.data, '$.text') as prompt_text
    FROM part pt
    JOIN message m ON m.id = pt.message_id
    JOIN session s ON s.id = pt.session_id
    LEFT JOIN project p ON p.id = s.project_id
    WHERE json_extract(m.data, '$.role') = 'user'
      AND json_extract(pt.data, '$.type') = 'text'
      AND json_extract(pt.data, '$.text') IS NOT NULL
    """
    params = []
    if q:
        sql += " AND lower(json_extract(pt.data, '$.text')) LIKE ?"
        params.append(f"%{q.lower()}%")
    if project_filter:
        sql += " AND (lower(p.worktree) LIKE ? OR lower(s.directory) LIKE ? OR lower(s.title) LIKE ?)"
        pf = f"%{project_filter.lower()}%"
        params.extend([pf, pf, pf])
    sql += " ORDER BY s.time_updated DESC, m.time_created DESC LIMIT ?"
    params.append(limit * 3)  # fetch extra then dedupe if needed
    cur.execute(sql, params)
    rows = cur.fetchall()
    # Deduplicate: one entry per prompt (message) — already per part, but keep as is, limit to requested
    out = []
    seen = set()
    for r in rows:
        key = (r["session_id"], r["prompt_text"][:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out

def format_row(r, idx):
    t = r["time_updated"] or r["time_created"] or r["msg_time"] or 0
    try:
        dt = datetime.datetime.fromtimestamp(int(t)/1000).strftime("%Y-%m-%d %H:%M")
    except:
        dt = str(t)
    # Prefer session_dir (actual working folder at session time) over project worktree.
    # For global project, worktree is "/" which is not useful.
    session_dir = r["session_dir"] or ""
    proj_wt = r["project_worktree"] or ""
    if proj_wt and proj_wt != "/" and proj_wt != "global" and session_dir and proj_wt.lower() not in session_dir.lower():
        proj = f"{session_dir} ({proj_wt})"
    else:
        proj = session_dir or proj_wt or "?"
    # shorten for table but keep full in JSON
    proj_short = proj
    if len(proj_short) > 38:
        # keep last segment + first char of parent for context
        parts = proj_short.replace("\\", "/").split("/")
        # Show last 2 meaningful parts
        meaningful = [p for p in parts if p]
        if len(meaningful) >= 2:
            proj_short = "/".join(meaningful[-2:])
        else:
            proj_short = proj_short[-38:]
    title = r["session_title"] or "(untitled)"
    if len(title) > 45:
        title = title[:42] + "…"
    snippet = normalize(r["prompt_text"] or "", 110)
    return f"{idx:2d} | {dt} | {proj_short:38s} | {title:45s} | {snippet:110s}"

def main():
    ap = argparse.ArgumentParser(description="SearchPro standalone — search user prompts with project context")
    ap.add_argument("query", nargs="?", help="search text (case-insensitive) in user prompts")
    ap.add_argument("--all", action="store_true", help="list most recent prompts (no filter)")
    ap.add_argument("--project", help="filter by project/worktree substring")
    ap.add_argument("--limit", type=int, default=20, help="max results (default 20)")
    ap.add_argument("--db", help="path to opencode.db (default: $OPENCODE_DB or ~/.local/share/opencode/opencode.db)")
    ap.add_argument("--json", action="store_true", help="output JSON")
    args = ap.parse_args()

    global DB
    if args.db:
        DB = args.db

    q = None if args.all else args.query
    if not q and not args.all:
        # interactive prompt
        try:
            q = input("Search prompts (leave empty for recent): ").strip()
            if not q:
                args.all = True
                q = None
        except: pass

    con = open_db()
    rows = query_prompts(con, q=q, limit=args.limit, project_filter=args.project)
    con.close()

    if args.json:
        import json as _json
        out = []
        for r in rows:
            out.append({k: r[k] for k in r.keys()})
        print(_json.dumps(out, indent=2, ensure_ascii=False))
        return

    if not rows:
        print("No matching prompts found.")
        if q:
            print(f"  query: '{q}'  (searches user prompts only, not assistant)")
        return

    header = f"{'#':2s} | {'Time':16s} | {'Project (working folder)':38s} | {'Session Title':45s} | {'Prompt Snippet':110s}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    for i, r in enumerate(rows, 1):
        print(format_row(r, i))
    print(sep)
    print(f"\nFound {len(rows)} prompts" + (f" matching '{q}'" if q else " (recent)"))
    print("Projects shown are session.project_id -> project.worktree (working folder) and session.directory")
    print("\nTo open in opencode:")
    print("  Desktop Ctrl+B -> find working folder (Project column) -> open session by Session Title")

if __name__ == "__main__":
    main()
