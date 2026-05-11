#pragma once
#include <iostream>
#include <map>
#include <set>
#include <vector>
#include <string>
#include <mutex>
#include <queue>

namespace llmos {


struct Semaphore {
    std::string name;
    int  value;        
    int  holder_pid;   
    std::queue<int> wait_queue;  

    explicit Semaphore(const std::string& n, int init = 1)
        : name(n), value(init), holder_pid(-1) {}
};









class SemaphoreManager {
public:
    
    bool create(const std::string& name, int init_value = 1) {
        std::lock_guard<std::mutex> lock(mtx_);
        if (sems_.count(name)) return false;
        sems_.emplace(name, Semaphore(name, init_value));
        std::cout << "[Semaphore] Created '" << name
                  << "' init=" << init_value << "\n";
        return true;
    }

    
    bool wait(const std::string& name, int pid) {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = sems_.find(name);
        if (it == sems_.end()) {
            std::cout << "[Semaphore] wait: unknown '" << name << "'\n";
            return false;
        }
        auto& sem = it->second;
        if (sem.value > 0) {
            sem.value--;
            sem.holder_pid = pid;
            
            assignment_edges_[name].insert(pid);
            
            request_edges_[pid].erase(name);
            std::cout << "[Semaphore] PID=" << pid << " acquired '" << name << "'\n";
            return true;
        }
        
        sem.wait_queue.push(pid);
        request_edges_[pid].insert(name);
        std::cout << "[Semaphore] PID=" << pid
                  << " BLOCKED on '" << name << "'\n";
        _check_deadlock_nolock();
        return false;
    }

    
    void signal(const std::string& name, int pid) {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = sems_.find(name);
        if (it == sems_.end()) return;
        auto& sem = it->second;
        
        assignment_edges_[name].erase(pid);
        sem.holder_pid = -1;

        if (!sem.wait_queue.empty()) {
            int next = sem.wait_queue.front(); sem.wait_queue.pop();
            sem.holder_pid = next;
            assignment_edges_[name].insert(next);
            request_edges_[next].erase(name);
            std::cout << "[Semaphore] PID=" << pid << " released '" << name
                      << "'; PID=" << next << " now holds it\n";
        } else {
            sem.value++;
            std::cout << "[Semaphore] PID=" << pid
                      << " released '" << name << "'\n";
        }
    }

    
    bool check_deadlock() {
        std::lock_guard<std::mutex> lock(mtx_);
        return _check_deadlock_nolock();
    }

    void dump() const {
        std::lock_guard<std::mutex> lock(mtx_);
        std::cout << "\n[Semaphores] " << sems_.size() << " semaphore(s):\n";
        for (auto& [n, s] : sems_) {
            std::cout << "  '" << n << "'  val=" << s.value
                      << "  holder=" << s.holder_pid
                      << "  waiters=" << s.wait_queue.size() << "\n";
        }
    }

private:
    std::map<std::string, Semaphore>         sems_;
    std::map<std::string, std::set<int>>     assignment_edges_; 
    std::map<int,         std::set<std::string>> request_edges_;
    mutable std::mutex mtx_;

    
    bool _check_deadlock_nolock() {
        
        
        std::map<int, std::set<int>> waits_for;
        for (auto& [pid, res_set] : request_edges_) {
            for (auto& res : res_set) {
                auto ait = assignment_edges_.find(res);
                if (ait != assignment_edges_.end()) {
                    for (int holder : ait->second)
                        if (holder != pid) waits_for[pid].insert(holder);
                }
            }
        }
        if (waits_for.empty()) return false;

        std::set<int> visited, rec_stack;
        for (auto& [pid, _] : waits_for) {
            if (!visited.count(pid)) {
                std::vector<int> cycle;
                if (_dfs(pid, waits_for, visited, rec_stack, cycle)) {
                    std::cout << "\n[DEADLOCK DETECTED] Cycle: ";
                    for (int p : cycle) std::cout << "PID=" << p << " -> ";
                    std::cout << "PID=" << cycle.front() << "\n";
                    std::cout << "[Deadlock] Affected PIDs: ";
                    for (int p : cycle) std::cout << p << " ";
                    std::cout << "\n[Deadlock] Resolution: Consider preempting PID="
                              << cycle.back() << "\n\n";
                    return true;
                }
            }
        }
        return false;
    }

    bool _dfs(int node,
              const std::map<int,std::set<int>>& adj,
              std::set<int>& visited,
              std::set<int>& rec_stack,
              std::vector<int>& cycle) {
        visited.insert(node);
        rec_stack.insert(node);
        auto it = adj.find(node);
        if (it != adj.end()) {
            for (int nb : it->second) {
                if (!visited.count(nb)) {
                    if (_dfs(nb, adj, visited, rec_stack, cycle)) {
                        cycle.push_back(node); return true;
                    }
                } else if (rec_stack.count(nb)) {
                    cycle.push_back(nb); cycle.push_back(node); return true;
                }
            }
        }
        rec_stack.erase(node);
        return false;
    }
};


inline SemaphoreManager g_sem_manager;

} 
