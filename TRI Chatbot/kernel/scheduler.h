
#pragma once
#include <thread>
#include <atomic>
#include <chrono>
#include <iostream>
#include <functional>
#include <list>
#include <mutex>
#include "page_table.h"
#include "pcb.h"

namespace llmos {

struct BackgroundTask {
    std::string       name;
    std::thread       worker;
    std::atomic<bool> running{false};
    BackgroundTask(const std::string& n) : name(n) {}
    BackgroundTask(const BackgroundTask&) = delete;
    BackgroundTask& operator=(const BackgroundTask&) = delete;
};

class Scheduler {
public:
    
    Scheduler(PageTable& pt, ProcessTable& ptable, int time_quantum_ms = 500)
        : pt_(pt), ptable_(ptable),
          time_quantum_ms_(time_quantum_ms), stop_all_(false) {}

    ~Scheduler() { stop(); }

    void start() {
        std::cout << "[Scheduler] Starting — policy=Priority+RoundRobin"
                  << "  quantum=" << time_quantum_ms_ << "ms\n";
        _start_memory_monitor();
        _start_stats_printer();
        _start_scheduler_tick();
        std::cout << "[Scheduler] " << tasks_.size()
                  << " background thread(s) running.\n";
    }

    void stop() {
        stop_all_ = true;
        for (auto& t : tasks_) {
            t.running = false;
            if (t.worker.joinable()) t.worker.join();
        }
        std::cout << "[Scheduler] All threads stopped.\n";
    }

    void set_quantum(int ms) { time_quantum_ms_ = ms; }
    int  get_quantum()  const { return time_quantum_ms_; }

private:
    PageTable&            pt_;
    ProcessTable&         ptable_;
    int                   time_quantum_ms_;
    std::atomic<bool>     stop_all_;
    std::list<BackgroundTask> tasks_;

    
    void _start_memory_monitor() {
        tasks_.emplace_back("memory_monitor");
        auto& task = tasks_.back();
        task.running = true;
        task.worker = std::thread([&task, this]() {
            while (task.running && !stop_all_) {
                int   used = pt_.active_pages();
                int   cap  = pt_.capacity();
                float pct  = cap > 0 ? (100.0f * used / cap) : 0.0f;
                if (pct >= 90.0f)
                    std::cout << "[MemMonitor] WARNING RAM "
                              << used << "/" << cap
                              << " (" << (int)pct << "%) — eviction imminent"
                              << "  policy=" << policy_name(pt_.get_policy()) << "\n";
                else if (pct >= 70.0f)
                    std::cout << "[MemMonitor] RAM " << used << "/" << cap
                              << " (" << (int)pct << "%)\n";
                std::this_thread::sleep_for(std::chrono::seconds(10));
            }
        });
    }

    
    void _start_stats_printer() {
        tasks_.emplace_back("stats_printer");
        auto& task = tasks_.back();
        task.running = true;
        task.worker = std::thread([&task, this]() {
            std::this_thread::sleep_for(std::chrono::seconds(30));
            while (task.running && !stop_all_) {
                std::cout << "\n[Stats] RAM=" << pt_.active_pages()
                          << "/" << pt_.capacity()
                          << "  policy=" << policy_name(pt_.get_policy()) << "\n";
                
                auto ready = ptable_.get_ready_queue();
                if (!ready.empty()) {
                    std::cout << "[Stats] Ready queue (highest priority first): ";
                    for (int p : ready) std::cout << "PID=" << p << " ";
                    std::cout << "\n";
                }
                ptable_.dump_all();
                std::this_thread::sleep_for(std::chrono::seconds(30));
            }
        });
    }

    
    
    void _start_scheduler_tick() {
        tasks_.emplace_back("scheduler_tick");
        auto& task = tasks_.back();
        task.running = true;
        task.worker = std::thread([&task, this]() {
            int tick = 0;
            while (task.running && !stop_all_) {
                std::this_thread::sleep_for(
                    std::chrono::milliseconds(time_quantum_ms_));
                tick++;
                
                ptable_.age_ready_processes();

                
                if (tick % 10 == 0) {
                    auto ready = ptable_.get_ready_queue();
                    if (!ready.empty()) {
                        std::cout << "[Scheduler] Tick #" << tick
                                  << "  Ready queue: ";
                        for (int p : ready) {
                            llmos::PCB* pcb = ptable_.get(p);
                            if (pcb)
                                std::cout << "PID=" << p
                                          << "(eff_prio=" << pcb->effective_priority()
                                          << ") ";
                        }
                        std::cout << "\n";
                    }
                }
            }
        });
    }
};

} 
