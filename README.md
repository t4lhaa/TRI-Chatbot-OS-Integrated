# 🧠 LLM-OS v3 — Intelligent Hybrid Operating System

> An OS kernel written in C++17, enhanced with an LLM-powered AI agent layer.  
> Built for the Operating Systems course @ FAST-NUCES Karachi.

---


## 📐 Architecture

```
Browser / Web UI  (Flask + HTML/JS)
        │
   LLM Agent Layer  (Python · ReAct · ChromaDB · 12+ tools)
        │
  Kernel Bridge  (Python · live TCP or pure-Python simulation)
        │
  C++ Kernel  ──────────────────────────────────────────────
  ├── ProcessTable   (pcb.h)
  ├── PageTable      (page_table.h)  ──► VectorDB (vector_db.h)
  ├── Scheduler      (scheduler.h)
  ├── SemaphoreManager (semaphore.h)
  └── Syscall Handler  (syscall.h)
```

---

## ⚙️ OS Concepts Implemented

| Concept | Implementation |
|---------|---------------|
| Process Management | PCB · 5 states · PID · priority · aging ticks |
| CPU Scheduling | Priority + Round-Robin · 500 ms quantum · starvation prevention |
| Virtual Memory | Page table · 10 frames · valid/dirty/ref bits |
| Page Replacement | **LRU · FIFO · CLOCK · LFU** (switchable at runtime) |
| Synchronization | Named binary & counting semaphores · FIFO wait queues |
| Deadlock Detection | Resource-allocation graph · DFS cycle detection |
| System Calls | 14 syscalls across process / memory / semaphore / file I/O |
| IPC | TCP socket JSON-RPC on port 9000 |
| Multi-threading | 3 background threads: scheduler tick · memory monitor · stats |
| Thread Safety | `std::mutex` on all shared structures |

---

## 🗂️ Project Structure

```
.
├── kernel/
│   ├── kernel_server.cpp   # TCP listener + syscall dispatcher
│   ├── pcb.h               # Process Control Block + ProcessTable
│   ├── page_table.h        # Virtual memory + 4 replacement policies
│   ├── scheduler.h         # Priority+RR scheduler + background threads
│   ├── semaphore.h         # Semaphores + deadlock detection
│   ├── syscall.h           # 14 system call handlers
│   └── vector_db.h         # Secondary storage (semantic embeddings)
├── kernel_bridge.py        # Python ↔ C++ bridge (with simulation fallback)
├── agent.py                # LLM agent (ReAct · tools · ChromaDB memory)
├── run.py                  # Flask web app
├── index.html              # Browser UI
├── Makefile
└── requirements.txt
```

---

## 📊 Stats

- **14** system calls
- **4** page-replacement policies
- **3** background kernel threads
- **12+** LLM agent tools
- **25+** supported file formats

---

## 🛠️ Tech Stack

- **Kernel:** C++17 · pthreads · POSIX sockets
- **Bridge / Agent:** Python 3 · sentence-transformers · ChromaDB · OpenRouter API
- **Web:** Flask · HTML/JS
- **Build:** GNU Make · GCC
- **OS Target:** Linux / Ubuntu

---
