#pragma once
#include <string>
#include <vector>
#include <map>
#include <mutex>
#include <iostream>
#include <chrono>

namespace llmos {

enum class ProcessState { NEW, READY, RUNNING, WAITING, TERMINATED };

static std::string state_name(ProcessState s) {
    switch (s) {
        case ProcessState::NEW:        return "NEW";
        case ProcessState::READY:      return "READY";
        case ProcessState::RUNNING:    return "RUNNING";
        case ProcessState::WAITING:    return "WAITING";
        case ProcessState::TERMINATED: return "TERMINATED";
    }
    return "UNKNOWN";
}

struct PCB {
    int           pid;
    std::string   username;
    ProcessState  state;
    int           priority;         
    int           aging_ticks;      
    int           turn_count;
    int           page_faults;
    int           pages_swapped;
    long          created_at;
    long          last_active_at;
    std::vector<std::string> syscall_log;

    PCB() : pid(-1), state(ProcessState::NEW), priority(5), aging_ticks(0),
            turn_count(0), page_faults(0), pages_swapped(0),
            created_at(0), last_active_at(0) {}

    PCB(int p, const std::string& user, int prio = 5)
        : pid(p), username(user), state(ProcessState::NEW),
          priority(prio), aging_ticks(0), turn_count(0),
          page_faults(0), pages_swapped(0) {
        created_at = last_active_at = _now_ms();
    }

    
    
    int effective_priority() const {
        int boost = aging_ticks / 5;
        return std::max(0, priority - boost);
    }

    void log_syscall(const std::string& call) {
        syscall_log.push_back(call);
        if (syscall_log.size() > 10)
            syscall_log.erase(syscall_log.begin());
    }

    void print() const {
        std::cout << "\n── PCB [PID=" << pid << "] ──────────────────\n"
                  << "  user         : " << username       << "\n"
                  << "  state        : " << state_name(state) << "\n"
                  << "  priority     : " << priority
                  << "  (effective=" << effective_priority() << ")\n"
                  << "  aging_ticks  : " << aging_ticks     << "\n"
                  << "  turns        : " << turn_count      << "\n"
                  << "  page_faults  : " << page_faults     << "\n"
                  << "  pages_out    : " << pages_swapped   << "\n"
                  << "  last syscall : "
                  << (syscall_log.empty() ? "none" : syscall_log.back())
                  << "\n─────────────────────────────────────────\n";
    }

private:
    static long _now_ms() {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
    }
};

class ProcessTable {
public:
    int create(const std::string& username, int priority = 5) {
        std::lock_guard<std::mutex> lock(mtx_);
        int pid = next_pid_++;
        table_[pid] = PCB(pid, username, priority);
        table_[pid].state = ProcessState::READY;
        std::cout << "[Kernel] Process created PID=" << pid
                  << " user=" << username
                  << " priority=" << priority << "\n";
        return pid;
    }

    bool transition(int pid, ProcessState new_state) {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = table_.find(pid);
        if (it == table_.end()) return false;
        std::cout << "[Kernel] PID=" << pid << " "
                  << state_name(it->second.state) << " → "
                  << state_name(new_state) << "\n";
        it->second.state = new_state;
        it->second.last_active_at = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        return true;
    }

    
    void age_ready_processes() {
        std::lock_guard<std::mutex> lock(mtx_);
        for (auto& [pid, pcb] : table_) {
            if (pcb.state == ProcessState::READY)
                pcb.aging_ticks++;
        }
    }

    PCB* get(int pid) {
        auto it = table_.find(pid);
        return (it != table_.end()) ? &it->second : nullptr;
    }

    
    std::vector<int> get_ready_queue() {
        std::lock_guard<std::mutex> lock(mtx_);
        std::vector<int> ready;
        for (auto& [pid, pcb] : table_)
            if (pcb.state == ProcessState::READY) ready.push_back(pid);
        std::sort(ready.begin(), ready.end(), [this](int a, int b) {
            return table_[a].effective_priority() < table_[b].effective_priority();
        });
        return ready;
    }

    void dump_all() const {
        std::cout << "\n[ProcessTable] " << table_.size() << " process(es):\n";
        for (auto& [pid, pcb] : table_) pcb.print();
    }

private:
    int next_pid_ = 1000;
    std::map<int, PCB> table_;
    mutable std::mutex mtx_;
};

} 
