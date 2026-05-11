# LLM-OS v3: Comprehensive Operating System Project

## Executive Summary

LLM-OS v3 is a sophisticated hybrid operating system that combines an LLM-powered agentic AI layer with a full-featured C++ kernel. The project demonstrates core OS concepts including process management, memory virtualization, CPU scheduling, synchronization primitives, and system calls—while integrating modern AI capabilities for intelligent task execution and long-term knowledge retention.

---

## Project Architecture Overview

The system consists of four integrated layers:

1. **AI Agent Layer** (Python) - Intelligent task execution with RAG
2. **Kernel Bridge** (Python) - Interface layer to C++ kernel with fallback simulation
3. **C++ Kernel** - Core OS with multitasking and virtual memory
4. **Web Interface** (Flask) - Browser-based dashboard and user management

---

## Core OS Components

### 1. Process Management (PCB - Process Control Block)

**File:** `kernel/pcb.h`

#### Features:
- **Process States**: NEW → READY → RUNNING → WAITING → TERMINATED
- **Process Identifiers**: Each process has a unique PID
- **Process Metadata**:
  - Username (process owner)
  - Priority level (0-10, where 0 is highest)
  - Aging ticks (for priority boost prevention)
  - Turn count (execution quantum tracking)
  - Page fault count (memory access monitoring)
  - Pages swapped (secondary storage tracking)
  - Timestamps (creation and last activity)
  - Syscall log (last 10 syscalls per process)

#### Priority Scheduling:
- **Effective Priority** = Base Priority - (Aging Ticks / 5)
- Prevents process starvation through automatic priority boosting
- Lower effective priority = higher scheduling precedence

#### Process Table:
- Thread-safe mutex-protected process table
- Supports dynamic process creation with user association
- State transition validation and tracking

---

### 2. CPU Scheduling

**File:** `kernel/scheduler.h`

#### Scheduling Policy:
- **Priority + Round-Robin Preemptive Scheduling**
- Time quantum: 500ms (configurable)
- Processes cycle through READY queue based on effective priority

#### Scheduler Components:

**Memory Monitor Thread:**
- Continuously monitors RAM usage
- Issues warnings when usage exceeds 70% and 90%
- Tracks memory pressure and eviction policy effectiveness
- Updates at 10-second intervals

**Statistics Printer Thread:**
- Periodic collection of system metrics
- Process queue status reporting
- Real-time performance statistics

**Scheduler Tick Thread:**
- Core scheduling mechanism
- Manages time quantum expiration
- Enforces preemption and context switching
- Updates process aging ticks

#### Features:
- Multiple background threads for concurrent operation
- Atomic operations for thread safety
- Clean shutdown protocol

---

### 3. Virtual Memory Management

**File:** `kernel/page_table.h`

#### Memory Architecture:
- **RAM Capacity**: Configurable frame count (default: 10 frames)
- **Physical Memory**: Fixed frame size storage
- **Virtual Memory**: Secondary storage via VectorDB

#### Page Replacement Policies:

1. **LRU (Least Recently Used)**
   - Evicts page with oldest access time
   - Optimal for temporal locality workloads
   - Requires timestamp tracking per access

2. **FIFO (First-In-First-Out)**
   - Evicts oldest resident page
   - Simple overhead, predictable behavior
   - Suitable for sequential access patterns

3. **CLOCK (Second Chance)**
   - Uses reference bits and clock hand pointer
   - Approximates LRU with lower overhead
   - Balances performance and accuracy

4. **LFU (Least Frequently Used)**
   - Evicts page with lowest access frequency counter
   - Favors hot working sets
   - Tracks frequency statistics

#### Page Table Operations:
- `insert()` - Allocate page with automatic eviction
- `access()` - Read page with LRU touch update
- `page_out()` - Explicit deallocate and swap to disk
- Thread-safe with mutex locking
- Returns evicted page ID for process tracking

#### Page Entry Structure:
- Page ID and Frame ID mapping
- Valid/Dirty/Reference bits
- Last access timestamp
- Frequency counter
- Content storage

---

### 4. Process Synchronization

**File:** `kernel/semaphore.h`

#### Synchronization Primitives:
- **Binary Semaphores** (mutex-like): init value = 1
- **Counting Semaphores** (resource pools): init value = N

#### Semaphore Manager Features:

**Core Operations:**
- `create(name, init_value)` - Create named semaphore
- `wait(name, pid)` - Acquire semaphore (decrement value)
- `signal(name, pid)` - Release semaphore (increment value)

**Wait Queue Management:**
- FIFO queue for blocked processes
- Process transitions to WAITING state
- Automatic state transition on acquisition

**Deadlock Detection:**
- Assignment edges: semaphore → process (holds resource)
- Request edges: process → semaphore (waiting for resource)
- Cycle detection in resource allocation graph
- Prevents circular wait conditions

#### Thread Safety:
- Mutex-protected semaphore map
- Atomic operations on value and queue
- Guard against race conditions

---

### 5. System Call Interface (Syscall Handler)

**File:** `kernel/syscall.h`

#### Implemented System Calls:

**Process Management Syscalls:**
- `proc_fork` - Create new process with specified priority
- `proc_run` - Transition process to RUNNING state
- `proc_wait` - Transition process to WAITING state
- `proc_ready` - Transition process to READY state
- `proc_exit` - Terminate process (TERMINATED state)
- `proc_status` - Query PCB information (state, priority, stats)

**Memory Management Syscalls:**
- `mem_alloc` - Allocate virtual page with automatic eviction tracking
- `mem_alloc_full` - Full memory allocation with content
- `mem_read` - Access page with page fault detection
- `mem_free` - Deallocate page to secondary storage

**Semaphore Syscalls:**
- `sem_create` - Create named semaphore
- `sem_wait` - Acquire semaphore (blocks if unavailable)
- `sem_signal` - Release semaphore
- `sem_destroy` - Destroy semaphore

**File I/O Syscalls:**
- `fs_read` - Read file content
- `fs_write` - Write file content
- `fs_delete` - Delete file

#### Syscall Result Format:
- Status indicator (success/failure)
- JSON-formatted response data
- Error messages with failure reasons
- Process tracking and logging

---

### 6. Vector Database (VectorDB) - Secondary Storage

**File:** `kernel/vector_db.h`

#### Purpose:
- Manages secondary storage (disk) for evicted pages
- Provides semantic similarity search
- Enables intelligent page recall

#### Text Embedding Layer:
- **TextEmbedder Class**: Converts text to vector representations
- Vocabulary construction from training text
- Tokenization with word filtering

#### Vector Operations:
- **Embedding Generation**: Text → Dense vector
- **Cosine Similarity**: Measure vector distance
- Vector normalization for consistency

#### Storage Features:
- Thread-safe embedding operations (mutex-protected)
- Dynamic vocabulary expansion
- Supports similarity-based page retrieval
- Bridges semantic search with storage management

---

## Kernel-Level Features

### Multi-threaded Kernel Architecture:
- **Main Thread**: Accepts TCP connections and syscall dispatch
- **Scheduler Thread**: Manages preemption and context switching
- **Memory Monitor Thread**: RAM pressure tracking
- **Statistics Thread**: System metrics collection
- All threads synchronized with atomic operations

### IPC (Inter-Process Communication):
- TCP socket-based syscall transmission
- JSON serialization for cross-layer communication
- Port 9000 for kernel bridge connection

### Kernel Boot Process:
- Process table initialization
- Page table initialization with selected replacement policy
- Semaphore manager setup
- Scheduler startup with background threads
- Kernel bridge connection advertisement

---

## Python Kernel Bridge Layer

**File:** `kernel_bridge.py`

### Dual-Mode Operation:

**Live Mode (C++ Kernel Active):**
- Connects to kernel_server on TCP port 9000
- Forwards syscalls to native kernel
- Real-time process and memory management
- Native scheduling and paging

**Simulation Mode (Fallback):**
- Emulates all OS functionality in Python
- Maintains in-memory process table
- Simulates RAM with eviction policies
- Simulates scheduler behavior
- Enables development without C++ compilation

### Features:
- Connection pooling with automatic retry
- Colored console output for clarity
- Syscall logging and tracing
- Process and memory state visualization
- Real-time PCB snapshots
- LRU page eviction with timestamp tracking

---

## LLM Agent Layer

**File:** `agent.py`

### AI Integration Features:

**Tool Ecosystem:**
- Calculator (math expressions)
- Web search (DuckDuckGo)
- Wikipedia retrieval
- Weather API integration
- News API fetching
- Country information lookup
- Currency conversion
- Word definitions
- Local file reading
- ChromaDB semantic memory

### Memory Management (ChromaDB):
- **Persistent Memory**: Vector database of past interactions
- **User-Scoped Collections**: Per-user memory isolation
- **Semantic Retrieval**: Cosine similarity search
- **Memory Saving**: Store insights with source attribution
- **Threshold Filtering**: Configurable similarity threshold (0.45)

### Agentic Execution:
- **ReAct Framework**: Reasoning + Acting loop
- **Max Steps**: 10 iterations per query
- **Active Turns**: Track conversation state
- **Model**: OpenRouter API (GPT-4o-mini)
- **Embeddings**: Sentence-transformers (all-MiniLM-L6-v2)

### Tool Integration:
- 12+ structured tools with JSON schemas
- Automatic tool calling via LLM
- Error handling and validation
- Graceful fallbacks

---

## Web Interface & User Management

**File:** `run.py` (Flask application)

### Frontend (HTML/JavaScript):
- Interactive chat interface
- File upload support (documents, images, code)
- User authentication and session management
- Multi-format file processing

### Backend Services:

**User Management:**
- Registration with age/gender/username validation
- Password hashing (SHA-256)
- Per-user chat history isolation
- Session persistence

**File Handling:**
- Image support: jpg, png, gif, webp, bmp
- Text files: code, markdown, data formats (CSV, JSON, XML, YAML)
- Binary support: PDF, Word, Excel, PowerPoint
- Base64 encoding for transfer
- Multipart form upload (50MB limit)

**Chat Features:**
- Message history persistence
- User-specific memory scoping
- Multi-turn conversations
- File context integration

### CORS & Security:
- Cross-Origin Resource Sharing enabled
- Session-based authentication
- Secure cookie handling
- Input validation on all endpoints

---

## System Dependencies

**Python Packages:**
- `openai` - API client for LLM calls
- `sentence-transformers` - Text embedding model
- `chromadb` - Vector database for memory
- `flask`, `flask-cors` - Web framework
- `requests`, `wikipedia`, `duckduckgo-search` - Data sources
- `python-dotenv` - Environment configuration
- `Pillow`, `PyMuPDF`, `python-docx`, `openpyxl` - Document processing

**C++ Requirements:**
- C++17 standard
- POSIX threads (pthread)
- Standard library (algorithm, chrono, map, vector, mutex, queue)
- TCP socket API

---

## Build & Execution

**Building the C++ Kernel:**
```bash
make              # Compile with LRU policy (default)
make run          # Build and run with LRU
make run-fifo     # Build and run with FIFO
make run-clock    # Build and run with CLOCK
make run-lfu      # Build and run with LFU
make clean        # Clean build artifacts
```

**Running the System:**
1. Start kernel: `./kernel_server --policy LRU --quantum 500`
2. Run web app: `python run.py`
3. Access UI: `http://localhost:5000`

**Simulation Mode:**
- Automatic fallback if kernel unavailable
- No compilation required
- Full functionality in Python

---

## Key OS Concepts Demonstrated

| Concept | Implementation |
|---------|-----------------|
| **Process Management** | PCB state machine, process creation/termination |
| **Process Scheduling** | Priority + Round-Robin with time quantum |
| **Priority Starvation** | Aging ticks boost low-priority processes |
| **Virtual Memory** | Page table with physical-virtual mapping |
| **Page Replacement** | LRU/FIFO/CLOCK/LFU policies |
| **Memory Eviction** | Automatic secondary storage (VectorDB) |
| **Synchronization** | Semaphores with wait queues |
| **Deadlock Detection** | Resource allocation graph cycle detection |
| **System Calls** | Process, memory, semaphore, file I/O syscalls |
| **IPC** | TCP socket-based syscall RPC |
| **Multi-threading** | Kernel threads for scheduling/monitoring |
| **Thread Safety** | Mutex-protected shared data structures |

---

## Performance Characteristics

- **Time Quantum**: 500ms (configurable)
- **RAM Capacity**: 10 frames (configurable)
- **Memory Monitoring**: Every 10 seconds
- **Statistics Update**: Every 30 seconds
- **TCP Timeout**: 0.8 seconds
- **Similarity Threshold**: 0.45 (cosine similarity)
- **Max Conversation Steps**: 10 iterations
- **Max Active Turns**: 10

---

## Innovation: LLM Integration

Unlike traditional OS kernels, LLM-OS v3 uniquely combines:
- **Semantic Understanding**: Agent can reason about system state using NLP
- **Long-term Memory**: ChromaDB preserves conversation history with vector similarity
- **Intelligent Tools**: Agent can query weather, news, web, and system APIs
- **Multi-user Support**: User-scoped memory and session isolation
- **Document Processing**: Handle code, PDFs, spreadsheets, images
- **Hybrid Execution**: Seamless kernel switching between native and simulation modes

---

## Project Statistics

- **Total Lines of Code**: ~3,500+ (C++ kernel: ~1,500, Python: ~2,000)
- **System Calls Implemented**: 14
- **Memory Policies**: 4
- **Synchronization Primitives**: 2 (binary + counting semaphores)
- **Background Threads**: 4
- **Tool Functions**: 12+
- **File Format Support**: 25+

---

## Conclusion

LLM-OS v3 demonstrates a production-grade operating system kernel enhanced with intelligent AI capabilities. It showcases:
- **Solid OS Fundamentals**: Full process, memory, scheduling management
- **Production Quality**: Thread safety, error handling, logging
- **Modern Architecture**: Microservices via TCP, fallback simulation, web interface
- **AI Integration**: LLM-powered agents with semantic memory
- **Extensibility**: Pluggable memory policies, configurable parameters, modular design

The system serves as both a functional OS implementation and an intelligent agent platform, bridging traditional systems programming with modern AI techniques.
