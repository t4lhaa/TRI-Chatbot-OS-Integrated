from __future__ import annotations
import socket
import json
import threading
import time
from datetime import datetime

KERNEL_HOST = "127.0.0.1"
KERNEL_PORT = 9000
TIMEOUT     = 0.8

_lock      = threading.Lock()
_sock      = None
_connected = False
_boot_shown = False     
_call_counter = 0           

_sim_pid_counter   = 2000
_sim_processes: dict[int, dict] = {}
_sim_ram: dict[int, str]  = {}        
_sim_disk: dict[int, str] = {}   
RAM_CAP = 10

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"

_BLACK   = "\033[30m"
_RED     = "\033[31m"
_GREEN   = "\033[32m"
_YELLOW  = "\033[33m"
_BLUE    = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN    = "\033[36m"
_WHITE   = "\033[37m"

_BG_BLACK  = "\033[40m"
_BG_RED    = "\033[41m"
_BG_GREEN  = "\033[42m"
_BG_BLUE   = "\033[44m"
_BG_CYAN   = "\033[46m"


def _c(text: str, *codes: str) -> str:
    return "".join(codes) + text + _RESET


def _ts() -> str:
    """Compact timestamp  HH:MM:SS.mmm"""
    now = datetime.now()
    return f"{now.strftime('%H:%M:%S')}.{now.microsecond // 1000:03d}"


def _seq() -> str:
    global _call_counter
    _call_counter += 1
    return f"{_call_counter:04d}"

def _banner():
    """Print the kernel boot banner (once)."""
    global _boot_shown
    if _boot_shown:
        return
    _boot_shown = True
    w = 62
    print()
    print(_c("=" * w, _CYAN, _BOLD))
    print(_c("  LLM-OS Kernel Bridge  —  Connected to C++ Kernel", _CYAN, _BOLD))
    print(_c(f"  Host: {KERNEL_HOST}:{KERNEL_PORT}   Mode: LIVE (TCP)", _CYAN))
    print(_c("  RAM Frames : 10   |   Eviction : LRU", _CYAN))
    print(_c("  [✓] PCB State Machine     [✓] LRU Page Table", _GREEN))
    print(_c("  [✓] VectorDB (C++ Cosine) [✓] Scheduler Threads", _GREEN))
    print(_c("  [✓] TCP Syscall IPC       [✓] FS Syscalls", _GREEN))
    print(_c("=" * w, _CYAN, _BOLD))
    print()


def _sim_banner():
    """Shown when kernel is offline and simulation kicks in."""
    global _boot_shown
    if _boot_shown:
        return
    _boot_shown = True
    w = 62
    print()
    print(_c("=" * w, _YELLOW, _BOLD))
    print(_c("  LLM-OS  —  SIMULATION MODE  (C++ Kernel offline)", _YELLOW, _BOLD))
    print(_c("  All OS syscalls are emulated in Python", _YELLOW))
    print(_c("  Start kernel:  cd kernel && make && ./kernel_server", _DIM))
    print(_c("=" * w, _YELLOW, _BOLD))
    print()


def _log_syscall(syscall: str, pid: int, extra: str = "", ok: bool = True):
    """Print a one-line syscall log entry."""
    seq    = _seq()
    status = _c("  OK  ", _BG_GREEN, _BLACK, _BOLD) if ok else _c(" FAIL ", _BG_RED, _WHITE, _BOLD)
    pid_s  = _c(f"PID={pid:<5}", _MAGENTA, _BOLD) if pid >= 0 else _c("PID=N/A  ", _DIM)
    call_s = _c(f"{syscall:<18}", _CYAN, _BOLD)
    ts_s   = _c(f"[{_ts()}]", _DIM)
    seq_s  = _c(f"#{seq}", _DIM)
    extra_s = _c(f"  ↳ {extra}", _DIM) if extra else ""
    print(f"  {ts_s} {seq_s} {status} {call_s} {pid_s}{extra_s}")


def _print_pcb_table(pid: int, user: str, state: str,
                     turns: int, faults: int, swapped: int,
                     source: str = "kernel"):
    """Print a neat PCB info table."""
    STATE_COLORS = {
        "NEW":        (_BLUE,    "◆"),
        "READY":      (_GREEN,   "●"),
        "RUNNING":    (_CYAN,    "▶"),
        "WAITING":    (_YELLOW,  "⏸"),
        "TERMINATED": (_RED,     "✕"),
    }
    col, sym = STATE_COLORS.get(state.upper(), (_WHITE, "?"))
    state_s  = _c(f"{sym} {state}", col, _BOLD)

    print()
    print(_c("  ┌─── PCB Snapshot " + "─" * 42, _BLUE))
    print(_c(f"  │  PID        : ", _BLUE) + _c(str(pid), _MAGENTA, _BOLD))
    print(_c(f"  │  User       : ", _BLUE) + _c(user, _WHITE))
    print(_c(f"  │  State      : ", _BLUE) + state_s)
    print(_c(f"  │  Turns      : ", _BLUE) + _c(str(turns), _WHITE))
    print(_c(f"  │  Page Faults: ", _BLUE) + _c(str(faults), _RED if faults > 0 else _GREEN))
    print(_c(f"  │  Pages Out  : ", _BLUE) + _c(str(swapped), _YELLOW if swapped > 0 else _GREEN))
    print(_c(f"  │  Source     : ", _BLUE) + _c(source, _DIM))
    print(_c("  └" + "─" * 58, _BLUE))
    print()


def _print_ram_table(ram_used: int, ram_cap: int, disk_pages: int, evicted: int = -1):
    """Print a RAM usage bar with stats."""
    filled   = int(20 * ram_used / max(ram_cap, 1))
    bar_fill = _c("█" * filled, _GREEN if filled < 15 else _YELLOW if filled < 19 else _RED)
    bar_empty = _c("░" * (20 - filled), _DIM)
    evict_s  = _c(f"  LRU evicted page={evicted}", _YELLOW, _BOLD) if evicted >= 0 else ""
    disk_s   = _c(f"{disk_pages}", _YELLOW, _BOLD)

    print()
    print(_c("  ┌─── Memory Manager (LRU Page Table) " + "─" * 23, _MAGENTA))
    print(_c(f"  │  RAM  [{bar_fill}{bar_empty}] {ram_used}/{ram_cap} frames", _MAGENTA))
    print(_c(f"  │  Disk (VectorDB) : ", _MAGENTA) + disk_s + _c(" pages on secondary storage", _DIM))
    if evict_s:
        print(_c("  │ ", _MAGENTA) + evict_s)
    print(_c("  └" + "─" * 58, _MAGENTA))
    print()


def _print_page_event(event: str, page_id: int, method: str = "", score: float = 0.0):
    """Print a page-fault / page-in / page-out event."""
    icons = {
        "fault":   (_RED,     "⚡ PAGE FAULT"),
        "page_in": (_GREEN,   "↑  PAGE IN  "),
        "page_out":(_YELLOW,  "↓  PAGE OUT "),
        "hit":     (_CYAN,    "✓  RAM HIT  "),
    }
    col, label = icons.get(event, (_WHITE, event))
    detail = ""
    if method:
        detail += f"  method={_c(method, _WHITE, _BOLD)}"
    if score > 0:
        detail += f"  cosine_sim={_c(f'{score:.4f}', _CYAN, _BOLD)}"
    print()
    print(_c(f"  ▌ {label} ", col, _BOLD) +
          _c(f" page={page_id}", _WHITE) + detail)
    print()


def _print_fs_event(op: str, path: str, size: int = 0, ok: bool = True):
    """Print a filesystem syscall result."""
    col   = _GREEN if ok else _RED
    sym   = "📄" if op == "read" else "💾"
    size_s = _c(f"  ({size} bytes)", _DIM) if size > 0 else ""
    status = _c("OK", col, _BOLD) if ok else _c("FAILED", _RED, _BOLD)
    print()
    print(_c(f"  ┌─── FS Syscall: {op.upper()} ", _BLUE) + _c("─" * 40, _BLUE))
    print(_c(f"  │  {sym}  Path   : ", _BLUE) + _c(path, _WHITE))
    print(_c(f"  │     Status : ", _BLUE) + status + size_s)
    print(_c("  └" + "─" * 58, _BLUE))
    print()


def _print_search_results(results: list):
    """Print cosine similarity search results from VectorDB."""
    print()
    print(_c("  ┌─── VectorDB Cosine-Similarity Search Results " + "─" * 14, _CYAN))
    if not results:
        print(_c("  │  (no results found on disk)", _DIM))
    else:
        for i, r in enumerate(results):
            pid  = r.get("page_id", "?")
            sc   = r.get("score", 0.0)
            snip = str(r.get("content", ""))[:55]
            bar  = int(sc * 10) * "▓" + (10 - int(sc * 10)) * "░"
            col  = _GREEN if sc > 0.5 else _YELLOW if sc > 0.25 else _RED
            print(_c(f"  │  [{i+1}] page={pid:<4} ", _CYAN) +
                  _c(f"sim=[{bar}] {sc:.4f}", col) +
                  _c(f'  "{snip}…"', _DIM))
    print(_c("  └" + "─" * 58, _CYAN))
    print()


def _print_kernel_stats(ram_used: int, ram_cap: int, disk_pages: int):
    """End-of-turn kernel summary box."""
    pct = int(100 * ram_used / max(ram_cap, 1))
    print()
    print(_c("  ╔═══ KERNEL STATS " + "═" * 44, _BLUE, _BOLD))
    print(_c(f"  ║  RAM  : {ram_used}/{ram_cap} frames ({pct}% utilised)", _BLUE))
    print(_c(f"  ║  Disk : {disk_pages} page(s) in VectorDB secondary storage", _BLUE))
    print(_c(f"  ║  Time : {_ts()}", _BLUE))
    print(_c("  ╚" + "═" * 58, _BLUE, _BOLD))
    print()


def _print_scheduler_tick(pid: int, old_state: str, new_state: str):
    """Print a state transition arrow."""
    STATE_COLORS = {
        "NEW":        _BLUE,
        "READY":      _GREEN,
        "RUNNING":    _CYAN,
        "WAITING":    _YELLOW,
        "TERMINATED": _RED,
    }
    old_c = STATE_COLORS.get(old_state.upper(), _WHITE)
    new_c = STATE_COLORS.get(new_state.upper(), _WHITE)
    print()
    print(_c("  ⚙  Scheduler ", _MAGENTA, _BOLD) +
          _c(f"PID={pid}", _MAGENTA) +
          _c("  ", _RESET) +
          _c(old_state, old_c, _BOLD) +
          _c("  ──►  ", _DIM) +
          _c(new_state, new_c, _BOLD))
    print()

def _connect() -> bool:
    global _sock, _connected
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect((KERNEL_HOST, KERNEL_PORT))
        _sock      = s
        _connected = True
        _banner()
        return True
    except Exception:
        _connected = False
        _sim_banner()
        return False


def _syscall_raw(payload: dict) -> dict:
    """Send one JSON syscall to the C++ kernel, return response dict."""
    global _sock, _connected

    if not _connected:
        _connect()
    if not _connected:
        return {"ok": False, "error": "kernel_offline"}

    try:
        with _lock:
            msg = json.dumps(payload) + "\n"
            _sock.sendall(msg.encode())
            raw = b""
            while True:
                chunk = _sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
                if raw.endswith(b"\n"):
                    break
            return json.loads(raw.decode().strip())
    except Exception as e:
        _connected = False
        return {"ok": False, "error": str(e)}


def _parse_data(res: dict) -> dict:
    """Safely parse the 'data' field which may be a JSON string or dict."""
    d = res.get("data", {})
    if isinstance(d, str):
        try:
            return json.loads(d)
        except Exception:
            return {}
    return d if isinstance(d, dict) else {}


def is_kernel_online() -> bool:
    if not _connected:
        _connect()
    return _connected

def _sim_proc_fork(username: str, priority: int = 5) -> int:
    global _sim_pid_counter
    pid = _sim_pid_counter
    _sim_pid_counter += 1
    _sim_processes[pid] = {
        "pid": pid, "username": username, "state": "READY",
        "priority": priority, "turns": 0, "faults": 0, "swapped": 0,
    }
    return pid


def _sim_state(pid: int, state: str):
    if pid in _sim_processes:
        _sim_processes[pid]["state"] = state


def _sim_mem_alloc(pid: int, page_id: int, content: str) -> int:
    evicted = -1
    if page_id not in _sim_ram:
        if len(_sim_ram) >= RAM_CAP:
            victim = next(iter(_sim_ram))
            evicted = victim
            _sim_disk[victim] = _sim_ram.pop(victim)
            if pid in _sim_processes:
                _sim_processes[pid]["swapped"] += 1
    _sim_ram[page_id] = content
    _sim_disk[page_id] = content 
    return evicted


def _sim_mem_read(pid: int, page_id: int, query: str = "") -> dict:
    if page_id in _sim_ram:
        return {"status": "hit", "page_id": page_id, "content": _sim_ram[page_id]}
    if pid in _sim_processes:
        _sim_processes[pid]["faults"] += 1
    if page_id in _sim_disk:
        content = _sim_disk.pop(page_id)
        # evict LRU if needed
        if len(_sim_ram) >= RAM_CAP:
            victim = next(iter(_sim_ram))
            _sim_disk[victim] = _sim_ram.pop(victim)
        _sim_ram[page_id] = content
        return {"status": "page_in", "page_id": page_id,
                "method": "exact", "cosine_sim": 1.0, "content": content}
    if query and _sim_disk:
        q_words = set(query.lower().split())
        best_id, best_score = -1, -1.0
        for pid_d, txt in _sim_disk.items():
            t_words = set(txt.lower().split())
            overlap = len(q_words & t_words) / max(len(q_words | t_words), 1)
            if overlap > best_score:
                best_score, best_id = overlap, pid_d
        if best_id >= 0 and best_score > 0.05:
            content = _sim_disk.pop(best_id)
            if len(_sim_ram) >= RAM_CAP:
                victim = next(iter(_sim_ram))
                _sim_disk[victim] = _sim_ram.pop(victim)
            _sim_ram[best_id] = content
            return {"status": "page_in", "page_id": best_id,
                    "method": "cosine_search", "cosine_sim": round(best_score, 4),
                    "content": content}
    return {"error": f"page_fault:not_found:page={page_id}"}


def _sim_mem_search(query: str, top_k: int = 3) -> list:
    if not _sim_disk:
        return []
    q_words = set(query.lower().split())
    scored = []
    for pid_d, txt in _sim_disk.items():
        t_words = set(txt.lower().split())
        overlap = len(q_words & t_words) / max(len(q_words | t_words), 1)
        scored.append({"page_id": pid_d, "content": txt, "score": round(overlap, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

def proc_fork(username: str, priority: int = 5) -> int:
    """Syscall: proc_fork — create a new OS process (PCB) for a user session."""
    if is_kernel_online():
        res = _syscall_raw({"syscall": "proc_fork", "username": username,
                            "priority": str(priority)})
        data = _parse_data(res)
        pid  = int(data.get("pid", -1)) if res.get("ok") else -1
    else:
        pid = _sim_proc_fork(username, priority)

    _log_syscall("proc_fork", pid, f"user={username} prio={priority}", ok=pid >= 0)
    if pid >= 0:
        _print_pcb_table(pid, username, "READY", 0, 0, 0,
                         source="C++ Kernel" if is_kernel_online() else "Python Sim")
    return pid


def proc_run(pid: int) -> dict:
    """Syscall: proc_run — transition process to RUNNING."""
    if is_kernel_online():
        res = _syscall_raw({"syscall": "proc_run", "pid": str(pid)})
    else:
        _sim_state(pid, "RUNNING")
        res = {"ok": True}
    _log_syscall("proc_run", pid, "READY → RUNNING", ok=res.get("ok", False))
    _print_scheduler_tick(pid, "READY", "RUNNING")
    return res


def proc_wait(pid: int) -> dict:
    """Syscall: proc_wait — transition process to WAITING (awaiting LLM/tool)."""
    if is_kernel_online():
        res = _syscall_raw({"syscall": "proc_wait", "pid": str(pid)})
    else:
        _sim_state(pid, "WAITING")
        res = {"ok": True}
    _log_syscall("proc_wait", pid, "RUNNING → WAITING", ok=res.get("ok", False))
    _print_scheduler_tick(pid, "RUNNING", "WAITING")
    return res


def proc_ready(pid: int) -> dict:
    """Syscall: proc_ready — transition process to READY."""
    if is_kernel_online():
        res = _syscall_raw({"syscall": "proc_ready", "pid": str(pid)})
    else:
        _sim_state(pid, "READY")
        res = {"ok": True}
    _log_syscall("proc_ready", pid, "WAITING → READY", ok=res.get("ok", False))
    _print_scheduler_tick(pid, "WAITING", "READY")
    return res


def proc_exit(pid: int) -> dict:
    """Syscall: proc_exit — terminate a process (TERMINATED state)."""
    if is_kernel_online():
        res = _syscall_raw({"syscall": "proc_exit", "pid": str(pid)})
    else:
        _sim_state(pid, "TERMINATED")
        res = {"ok": True}
    _log_syscall("proc_exit", pid, "→ TERMINATED", ok=res.get("ok", False))
    _print_scheduler_tick(pid, "RUNNING", "TERMINATED")
    return res


def proc_status(pid: int) -> dict:
    """Syscall: proc_status — get PCB info for a process."""
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "proc_status", "pid": str(pid)})
        data = _parse_data(res)
    else:
        p    = _sim_processes.get(pid, {})
        data = {"pid": pid, "user": p.get("username","?"),
                "state": p.get("state","UNKNOWN"),
                "turns": p.get("turns", 0),
                "page_faults": p.get("faults", 0),
                "pages_swapped": p.get("swapped", 0)}
        res  = {"ok": True, "data": data}

    _log_syscall("proc_status", pid, f"state={data.get('state','?')}", ok=res.get("ok", False))
    _print_pcb_table(
        pid=data.get("pid", pid),
        user=data.get("user", data.get("username", "?")),
        state=data.get("state", "UNKNOWN"),
        turns=data.get("turns", 0),
        faults=data.get("page_faults", 0),
        swapped=data.get("pages_swapped", 0),
        source="C++ Kernel" if is_kernel_online() else "Python Sim",
    )
    return res

def mem_alloc(pid: int, page_id: int, content: str) -> dict:
    """
    Syscall: mem_alloc_full
    Allocates a page in RAM. Also backs up to VectorDB.
    LRU eviction fires if RAM is full.
    Maps to: PageTable::insert() + VectorDB::store() in kernel_server.cpp
    """
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "mem_alloc_full", "pid": str(pid),
                              "page_id": str(page_id), "content": content[:400]})
        data    = _parse_data(res)
        evicted = int(data.get("evicted_page", -1))
    else:
        evicted = _sim_mem_alloc(pid, page_id, content)
        res     = {"ok": True, "data": {"status": "allocated", "evicted_page": evicted}}

    ok = res.get("ok", False)
    _log_syscall("mem_alloc", pid,
                 f"page={page_id}  evicted={evicted if evicted >= 0 else 'none'}", ok=ok)

    # Show RAM table
    stat = _mem_status_raw()
    _print_ram_table(stat["ram_used"], stat["ram_cap"], stat["disk_pages"], evicted)

    if evicted >= 0:
        _print_page_event("page_out", evicted)

    return res


def mem_read(pid: int, page_id: int, query: str = "") -> dict:
    """
    Syscall: mem_read
    Read a page from RAM.  PAGE FAULT if missing → C++ cosine search on VectorDB.
    Maps to: PageTable::access() + handle_page_fault() in kernel_server.cpp
    """
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "mem_read", "pid": str(pid),
                              "page_id": str(page_id), "query": query})
        data = _parse_data(res)
        status = data.get("status", "")
    else:
        data   = _sim_mem_read(pid, page_id, query)
        status = data.get("status", "error")
        res    = {"ok": "error" not in data, "data": data}

    ok = res.get("ok", False)

    if status == "hit":
        _log_syscall("mem_read", pid, f"page={page_id}  → RAM HIT", ok=True)
        _print_page_event("hit", page_id)
    elif status == "page_in":
        method = data.get("method", "?")
        score  = float(data.get("cosine_sim", 0.0))
        _log_syscall("mem_read", pid,
                     f"page={page_id}  → PAGE FAULT → PAGE IN [{method}]", ok=True)
        _print_page_event("fault", page_id)
        _print_page_event("page_in", data.get("page_id", page_id), method, score)
    else:
        _log_syscall("mem_read", pid,
                     f"page={page_id}  → PAGE FAULT (not resolved)", ok=False)
        _print_page_event("fault", page_id)

    stat = _mem_status_raw()
    _print_ram_table(stat["ram_used"], stat["ram_cap"], stat["disk_pages"])
    return res


def mem_free(pid: int, page_id: int, content: str = "") -> dict:
    """
    Syscall: mem_free — explicitly page-out a page to VectorDB disk.
    Maps to: PageTable::page_out() + VectorDB::store() in kernel_server.cpp
    """
    if is_kernel_online():
        res = _syscall_raw({"syscall": "mem_free", "pid": str(pid),
                             "page_id": str(page_id), "content": content[:400]})
    else:
        if page_id in _sim_ram:
            _sim_disk[page_id] = _sim_ram.pop(page_id)
        if pid in _sim_processes:
            _sim_processes[pid]["swapped"] += 1
        res = {"ok": True, "data": {"status": "paged_out", "page_id": page_id}}

    _log_syscall("mem_free", pid, f"page={page_id}  → evict to VectorDB disk",
                 ok=res.get("ok", False))
    _print_page_event("page_out", page_id)
    stat = _mem_status_raw()
    _print_ram_table(stat["ram_used"], stat["ram_cap"], stat["disk_pages"])
    return res


def mem_search(query: str, top_k: int = 3) -> dict:
    """
    Syscall: mem_search — direct cosine similarity search on VectorDB disk.
    Maps to: VectorDB::search() + cosine_similarity() in vector_db.h
    """
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "mem_search", "query": query, "top_k": str(top_k)})
        data = _parse_data(res)
        results = data.get("results", [])
    else:
        results = _sim_mem_search(query, top_k)
        res = {"ok": True, "data": {"results": results}}

    _log_syscall("mem_search", -1,
                 f'query="{query[:40]}"  top_k={top_k}  hits={len(results)}',
                 ok=res.get("ok", False))
    _print_search_results(results)
    return res


def mem_status() -> dict:
    """Syscall: mem_status — get RAM and disk usage stats."""
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "mem_status"})
        data = _parse_data(res)
    else:
        data = {"ram_used": len(_sim_ram), "ram_capacity": RAM_CAP,
                "disk_pages": len(_sim_disk)}
        res  = {"ok": True, "data": data}

    stat = _mem_status_raw()
    _log_syscall("mem_status", -1,
                 f"RAM={stat['ram_used']}/{stat['ram_cap']}  disk={stat['disk_pages']}",
                 ok=res.get("ok", True))
    _print_ram_table(stat["ram_used"], stat["ram_cap"], stat["disk_pages"])
    return res


def _mem_status_raw() -> dict:
    """Internal helper — returns mem stats without printing."""
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "mem_status"})
        data = _parse_data(res)
        return {"ram_used": int(data.get("ram_used", 0)),
                "ram_cap":  int(data.get("ram_capacity", 10)),
                "disk_pages": int(data.get("disk_pages", 0))}
    return {"ram_used": len(_sim_ram), "ram_cap": RAM_CAP, "disk_pages": len(_sim_disk)}

def fs_read(pid: int, path: str) -> dict:
    """Syscall: fs_read — read a file from local filesystem."""
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "fs_read", "pid": str(pid), "path": path})
        data = _parse_data(res)
        ok   = res.get("ok", False)
        size = data.get("size", 0)
    else:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            res  = {"ok": True, "data": {"status": "ok", "content": content[:4000],
                                         "size": len(content)}}
            ok, size = True, len(content)
        except Exception as e:
            res  = {"ok": False, "error": str(e)}
            ok, size = False, 0

    _log_syscall("fs_read", pid, f'path="{path}"', ok=ok)
    _print_fs_event("read", path, size, ok=ok)
    return res


def fs_write(pid: int, path: str, content: str) -> dict:
    """Syscall: fs_write — write/append to a file."""
    if is_kernel_online():
        res = _syscall_raw({"syscall": "fs_write", "pid": str(pid),
                            "path": path, "content": content})
        ok  = res.get("ok", False)
    else:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            res = {"ok": True, "data": {"status": "written", "bytes": len(content)}}
            ok  = True
        except Exception as e:
            res = {"ok": False, "error": str(e)}
            ok  = False

    _log_syscall("fs_write", pid, f'path="{path}"  bytes={len(content)}', ok=ok)
    _print_fs_event("write", path, len(content), ok=ok)
    return res


def kernel_stats() -> dict:
    """Syscall: kernel_stats — dump full kernel state."""
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "kernel_stats"})
        data = _parse_data(res)
        ram_used    = int(data.get("ram_used", 0))
        ram_cap     = int(data.get("ram_capacity", 10))
        disk_pages  = int(data.get("disk_pages", 0))
    else:
        ram_used    = len(_sim_ram)
        ram_cap     = RAM_CAP
        disk_pages  = len(_sim_disk)
        res = {"ok": True}

    _log_syscall("kernel_stats", -1,
                 f"RAM={ram_used}/{ram_cap}  disk={disk_pages}", ok=True)
    _print_kernel_stats(ram_used, ram_cap, disk_pages)
    return res


def kernel_manage_context(chat_history: list,
                           pid: int,
                           max_active: int = 10,
                           save_fn=None) -> list:
    """
    Drop-in replacement for agent.manage_context() with kernel integration.

    OS workflow per conversation turn:
      1. mem_alloc_full  → page every recent turn into kernel RAM
      2. LRU eviction    → kernel automatically pages out oldest turns
      3. mem_free        → explicitly page-out pre-eviction window turns
      4. proc_wait / proc_ready  → state transitions during swap
    """
    for i, msg in enumerate(chat_history[-max_active:]):
        content = msg.get("content", "")
        if isinstance(content, list):
            content = str(content)
        page_id = len(chat_history) - max_active + i
        if i >= len(chat_history[-max_active:]) - 2:
            mem_alloc(pid, page_id, content)

    if len(chat_history) <= max_active:
        return chat_history

    old    = chat_history[:-max_active]
    recent = chat_history[-max_active:]

    proc_wait(pid) 

    for i in range(0, len(old) - 1, 2):
        page_id = i
        u = old[i].get("content", "")
        if isinstance(u, list):
            u = str(u)
        a = old[i + 1].get("content", "") if i + 1 < len(old) else ""
        page_content = f"User: {u[:250]} | Agent: {a[:250]}"

        mem_free(pid, page_id, page_content)

        if save_fn:
            save_fn(page_content, source="offloaded_turn")

    proc_ready(pid) 
    return recent


_pid_registry:    dict[str, int]  = {}
_pid_state_cache: dict[int, str]  = {} 
_registry_lock = threading.Lock()


def get_or_create_pid(username: str) -> int:
    """
    Get the kernel PID for a user, creating one via proc_fork if needed.
    Called from run.py when a user logs in or sends a first message.
    """
    with _registry_lock:
        if username not in _pid_registry:
            pid = proc_fork(username)
            if pid > 0:
                _pid_registry[username] = pid
                proc_run(pid)
        return _pid_registry.get(username, -1)


def print_pid_registry():
    """Print all active user ↔ PID mappings."""
    if not _pid_registry:
        return
    print()
    print(_c("  ┌─── Active PID Registry " + "─" * 35, _GREEN))
    for uname, pid in _pid_registry.items():
        state = "RUNNING"
        if is_kernel_online():
            res  = _syscall_raw({"syscall": "proc_status", "pid": str(pid)})
            data = _parse_data(res)
            state = data.get("state", "?")
        elif pid in _sim_processes:
            state = _sim_processes[pid].get("state", "?")
        STATE_COLORS = {"RUNNING": _CYAN, "READY": _GREEN,
                        "WAITING": _YELLOW, "TERMINATED": _RED}
        col = STATE_COLORS.get(state.upper(), _WHITE)
        print(_c(f"  │  {uname:<16} ", _GREEN) +
              _c(f"PID={pid:<6}", _MAGENTA, _BOLD) +
              _c(state, col, _BOLD))
    print(_c("  └" + "─" * 58, _GREEN))
    print()


if __name__ == "__main__":
    print(_c("\n=== LLM-OS Kernel Bridge — Full Demo ===", _BOLD))
    print(_c(f"Kernel online: {is_kernel_online()}\n", _CYAN))

    if not is_kernel_online():
        print(_c("  NOTE: Running in simulation mode.", _YELLOW))
        print(_c("  To use real kernel:", _DIM))
        print(_c("    cd kernel && g++ -std=c++17 -pthread -o kernel_server kernel_server.cpp && ./kernel_server\n", _DIM))

    print(_c("\n[ Test 1: Process Lifecycle ]", _BOLD, _WHITE))
    pid = proc_fork("demo_user", priority=3)
    proc_run(pid)

    print(_c("\n[ Test 2: Memory Allocation — 12 pages, RAM cap=10 ]", _BOLD, _WHITE))
    for i in range(12):
        content = f"Turn {i}: The user asked about topic_{i} and the agent explained concepts."
        mem_alloc(pid, i, content)

    print(_c("\n[ Test 3: mem_read — expect RAM HIT ]", _BOLD, _WHITE))
    mem_read(pid, 11, query="topic_11")

    print(_c("\n[ Test 4: mem_read — expect PAGE FAULT → cosine search ]", _BOLD, _WHITE))
    mem_read(pid, 0, query="topic_0 explanation")

    print(_c("\n[ Test 5: Direct VectorDB cosine search ]", _BOLD, _WHITE))
    mem_search("topic_3 concepts", top_k=3)

    print(_c("\n[ Test 6: Filesystem syscalls ]", _BOLD, _WHITE))
    fs_write(pid, "/tmp/llmos_test.txt", "Hello from LLM-OS!\n")
    fs_read(pid, "/tmp/llmos_test.txt")

    print(_c("\n[ Test 7: Kernel Stats ]", _BOLD, _WHITE))
    kernel_stats()

    print(_c("\n[ Test 8: PCB Status ]", _BOLD, _WHITE))
    proc_status(pid)

    print(_c("\n[ Test 9: Process Exit ]", _BOLD, _WHITE))
    proc_exit(pid)
    print(_c("\n=== Demo Complete ===\n", _BOLD))


def set_policy(policy: str) -> dict:
    """
    Change the page-replacement policy in the C++ kernel at runtime.
    policy: one of 'LRU', 'FIFO', 'CLOCK', 'LFU'
    """
    policy = policy.upper()
    valid  = {"LRU", "FIFO", "CLOCK", "LFU"}
    if policy not in valid:
        print(_c(f"[set_policy] Invalid policy '{policy}'. Choose from {valid}", _RED))
        return {"ok": False, "error": "invalid_policy"}

    if is_kernel_online():
        res = _syscall_raw({"syscall": "set_policy", "policy": policy})
        ok  = res.get("ok", False)
    else:
        res = {"ok": True, "data": {"status": "policy_set", "policy": policy}}
        ok  = True

    seq_s  = _c(f"#{_seq()}", _DIM)
    ts_s   = _c(f"[{_ts()}]", _DIM)
    status = _c("  OK  ", _BG_GREEN, _BLACK, _BOLD) if ok else _c(" FAIL ", _BG_RED, _WHITE, _BOLD)
    call_s = _c(f"{'set_policy':<18}", _CYAN, _BOLD)
    print(f"  {ts_s} {seq_s} {status} {call_s} "
          + _c(f"policy={policy}", _YELLOW, _BOLD))
    return res


def sem_create(name: str, init_value: int = 1) -> dict:
    """Create a named semaphore in the kernel with given initial value."""
    if is_kernel_online():
        res = _syscall_raw({"syscall": "sem_create", "name": name,
                            "init_value": str(init_value)})
        ok  = res.get("ok", False)
    else:
        res = {"ok": True, "data": {"status": "created", "semaphore": name}}
        ok  = True

    _log_syscall("sem_create", -1, f"name='{name}'  init={init_value}", ok=ok)
    print("  " + _c(f"  Semaphore created: '{name}'  init_value={init_value}", _GREEN))
    return res


def sem_wait(name: str, pid: int) -> dict:
    """
    Acquire a named semaphore.
    If the semaphore is unavailable the kernel transitions the process
    to WAITING and the call returns {'acquired': False}.
    """
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "sem_wait", "name": name, "pid": str(pid)})
        ok   = res.get("ok", False)
        data = _parse_data(res)
        acquired = str(data.get("acquired", "false")).lower() == "true"
    else:
        # Simulation: always grant
        acquired = True
        res  = {"ok": True, "data": {"acquired": True, "semaphore": name}}
        ok   = True

    _log_syscall("sem_wait", pid,
                 f"name='{name}'  " + ("ACQUIRED" if acquired else "BLOCKED"), ok=ok)
    col = _GREEN if acquired else _YELLOW
    print("  " + _c(f"  SEM_WAIT '{name}' → "
                    + ("acquired ✓" if acquired else "BLOCKED (process waiting)"), col, _BOLD))
    return res


def sem_signal(name: str, pid: int) -> dict:
    """Release a named semaphore, waking the next waiting process if any."""
    if is_kernel_online():
        res = _syscall_raw({"syscall": "sem_signal", "name": name, "pid": str(pid)})
        ok  = res.get("ok", False)
    else:
        res = {"ok": True, "data": {"status": "ok"}}
        ok  = True

    _log_syscall("sem_signal", pid, f"name='{name}'", ok=ok)
    print("  " + _c(f"  SEM_SIGNAL '{name}' released", _CYAN))
    return res


def deadlock_check() -> dict:
    """
    Ask the kernel to run cycle detection on the Resource Allocation Graph.
    Returns {'deadlock_detected': True/False}.
    """
    if is_kernel_online():
        res  = _syscall_raw({"syscall": "deadlock_check"})
        ok   = res.get("ok", False)
        data = _parse_data(res)
        found = str(data.get("deadlock_detected", "false")).lower() == "true"
    else:
        found = False
        res   = {"ok": True, "data": {"deadlock_detected": False}}
        ok    = True

    _log_syscall("deadlock_check", -1,
                 "DEADLOCK FOUND!" if found else "no deadlock", ok=ok)
    col = _RED if found else _GREEN
    print("  " + _c("  [DEADLOCK CHECK] " +
                     ("⚠ DEADLOCK DETECTED" if found else "✓ No deadlock"), col, _BOLD))
    return res


def get_ready_queue() -> list[int]:
    """
    Return PIDs of all READY processes sorted by effective priority
    (uses proc_status checks on known PIDs from the registry).
    This is a Python-side helper — the kernel sorts internally.
    """
    with _registry_lock:
        pids = list(_pid_registry.values())

    ready = []
    for pid in pids:
        if is_kernel_online():
            res  = _syscall_raw({"syscall": "proc_status", "pid": str(pid)})
            data = _parse_data(res)
            if data.get("state", "").upper() == "READY":
                eff = int(data.get("eff_priority", 9))
                ready.append((eff, pid))
        elif pid in _sim_processes:
            if _sim_processes[pid].get("state", "") == "READY":
                ready.append((5, pid))

    ready.sort(key=lambda x: x[0])
    return [pid for _, pid in ready]
