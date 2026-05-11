#pragma once
#include <string>
#include <map>
#include <iostream>
#include <fstream>
#include <sstream>
#include "page_table.h"
#include "pcb.h"
#include "semaphore.h"

namespace llmos {

struct SyscallResult {
    bool        ok;
    std::string data;
    std::string error;
    static SyscallResult success(const std::string& d) { return {true, d, ""}; }
    static SyscallResult fail(const std::string& e)    { return {false, "", e}; }
};

class SyscallHandler {
public:
    SyscallHandler(PageTable& pt, ProcessTable& ptable, SemaphoreManager& semgr)
        : pt_(pt), ptable_(ptable), semgr_(semgr) {}

    SyscallResult dispatch(const std::string& sc,
                           const std::map<std::string,std::string>& p,
                           int pid = -1)
    {
        std::cout << "[Syscall] " << sc << " (PID=" << pid << ")\n";
        if (pid >= 0) { PCB* pcb = ptable_.get(pid); if (pcb) pcb->log_syscall(sc); }

        
        if (sc == "proc_fork") {
            std::string user = gp(p,"username","anon");
            int prio         = gi(p,"priority",5);
            int new_pid      = ptable_.create(user, prio);
            ptable_.transition(new_pid, ProcessState::READY);
            return SyscallResult::success(
                "{\"status\":\"forked\",\"pid\":" + std::to_string(new_pid) + "}");
        }
        if (sc=="proc_run")   { ptable_.transition(pid,ProcessState::RUNNING);    return ok_s(); }
        if (sc=="proc_wait")  { ptable_.transition(pid,ProcessState::WAITING);    return ok_s(); }
        if (sc=="proc_ready") { ptable_.transition(pid,ProcessState::READY);      return ok_s(); }
        if (sc=="proc_exit")  {
            ptable_.transition(pid,ProcessState::TERMINATED);
            return SyscallResult::success("{\"status\":\"terminated\",\"pid\":" + std::to_string(pid) + "}");
        }
        if (sc=="proc_status") {
            PCB* pp = ptable_.get(pid); if (!pp) return SyscallResult::fail("{\"error\":\"pid_not_found\"}");
            pp->print();
            return SyscallResult::success(
                "{\"pid\":"          + std::to_string(pp->pid) +
                ",\"user\":\""       + pp->username + "\"" +
                ",\"state\":\""      + state_name(pp->state) + "\"" +
                ",\"priority\":"     + std::to_string(pp->priority) +
                ",\"eff_priority\":" + std::to_string(pp->effective_priority()) +
                ",\"aging_ticks\":"  + std::to_string(pp->aging_ticks) +
                ",\"turns\":"        + std::to_string(pp->turn_count) +
                ",\"page_faults\":"  + std::to_string(pp->page_faults) +
                ",\"pages_swapped\":" + std::to_string(pp->pages_swapped) + "}");
        }

        
        if (sc=="mem_alloc"||sc=="mem_alloc_full") {
            int pgid=gi(p,"page_id"); std::string cont=gp(p,"content");
            int evicted=pt_.insert(pgid,cont);
            PCB* pcb=ptable_.get(pid); if(pcb&&evicted>=0) pcb->pages_swapped++;
            return SyscallResult::success("{\"status\":\"allocated\",\"evicted_page\":" + std::to_string(evicted) + "}");
        }
        if (sc=="mem_read") {
            int pgid=gi(p,"page_id"); auto r=pt_.access(pgid);
            if (!r) { PCB* pcb=ptable_.get(pid); if(pcb) pcb->page_faults++;
                      return SyscallResult::fail("{\"error\":\"page_fault\",\"page_id\":" + std::to_string(pgid) + "}"); }
            return SyscallResult::success("{\"status\":\"hit\",\"content\":\"" + esc(*r) + "\"}");
        }
        if (sc=="mem_free") {
            int pgid=gi(p,"page_id"); pt_.page_out(pgid);
            PCB* pcb=ptable_.get(pid); if(pcb) pcb->pages_swapped++;
            return SyscallResult::success("{\"status\":\"paged_out\",\"page_id\":" + std::to_string(pgid) + "}");
        }

        
        if (sc=="set_policy") {
            std::string pol=gp(p,"policy","LRU");
            ReplacementPolicy rp = ReplacementPolicy::LRU;
            if (pol=="FIFO")  rp=ReplacementPolicy::FIFO;
            if (pol=="CLOCK") rp=ReplacementPolicy::CLOCK;
            if (pol=="LFU")   rp=ReplacementPolicy::LFU;
            pt_.set_policy(rp);
            return SyscallResult::success("{\"status\":\"policy_set\",\"policy\":\"" + pol + "\"}");
        }

        
        if (sc=="sem_create") {
            std::string name=gp(p,"name"); int init=gi(p,"init_value",1);
            semgr_.create(name,init);
            return SyscallResult::success("{\"status\":\"created\",\"semaphore\":\"" + name + "\"}");
        }
        if (sc=="sem_wait") {
            std::string name=gp(p,"name");
            bool acquired=semgr_.wait(name,pid);
            if (!acquired) ptable_.transition(pid,ProcessState::WAITING);
            return SyscallResult::success("{\"acquired\":" + std::string(acquired?"true":"false") +
                                          ",\"semaphore\":\"" + name + "\"}");
        }
        if (sc=="sem_signal") {
            std::string name=gp(p,"name");
            semgr_.signal(name,pid);
            return ok_s();
        }
        if (sc=="deadlock_check") {
            bool found=semgr_.check_deadlock();
            return SyscallResult::success("{\"deadlock_detected\":" + std::string(found?"true":"false") + "}");
        }
        if (sc=="sem_dump") { semgr_.dump(); return ok_s(); }

        
        if (sc=="fs_read") {
            std::string path=gp(p,"path"); std::ifstream f(path);
            if (!f) return SyscallResult::fail("{\"error\":\"file_not_found\",\"path\":\"" + esc(path) + "\"}");
            std::ostringstream buf; buf<<f.rdbuf();
            return SyscallResult::success("{\"status\":\"ok\",\"content\":\"" + esc(buf.str().substr(0,2000)) + "\"}");
        }
        if (sc=="fs_write") {
            std::string path=gp(p,"path"),cont=gp(p,"content");
            std::ofstream f(path,std::ios::app); if (!f) return SyscallResult::fail("{\"error\":\"write_failed\"}");
            f<<cont;
            return SyscallResult::success("{\"status\":\"written\",\"bytes\":" + std::to_string(cont.size()) + "}");
        }

        return SyscallResult::fail("{\"error\":\"unknown_syscall\",\"call\":\"" + sc + "\"}");
    }

private:
    PageTable&        pt_;
    ProcessTable&     ptable_;
    SemaphoreManager& semgr_;

    std::string gp(const std::map<std::string,std::string>& p, const std::string& k, const std::string& d="") {
        auto it=p.find(k); return it!=p.end()?it->second:d;
    }
    int gi(const std::map<std::string,std::string>& p, const std::string& k, int d=0) {
        auto it=p.find(k); if(it==p.end()) return d;
        try{return std::stoi(it->second);}catch(...){return d;}
    }
    std::string esc(const std::string& s) {
        std::string o; for(char c:s){
            if(c=='"') o+="\\\""; else if(c=='\\') o+="\\\\";
            else if(c=='\n') o+="\\n"; else if(c=='\r') o+="\\r";
            else if(c=='\t') o+="\\t"; else o+=c; } return o;
    }
    SyscallResult ok_s() { return SyscallResult::success("{\"status\":\"ok\"}"); }
};

} 
