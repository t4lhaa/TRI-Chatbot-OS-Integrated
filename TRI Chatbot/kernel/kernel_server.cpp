#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <thread>
#include <map>
#include <cstring>
#include <atomic>
#include <chrono>

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <signal.h>

#include "page_table.h"
#include "pcb.h"
#include "vector_db.h"
#include "scheduler.h"
#include "semaphore.h"

static const int  PORT               = 9000;
static const int  RAM_FRAMES         = 10;
static const float PAGE_FAULT_SIM_THRESH = 0.15f;


llmos::ReplacementPolicy g_policy     = llmos::ReplacementPolicy::LRU;
llmos::PageTable         g_page_table(RAM_FRAMES, g_policy);
llmos::ProcessTable      g_proc_table;
llmos::VectorDB          g_vector_db;
llmos::SemaphoreManager& g_sem_mgr    = llmos::g_sem_manager;
llmos::Scheduler*        g_scheduler  = nullptr;
std::atomic<bool>        g_running(true);


std::map<std::string,std::string> parse_json(const std::string& json) {
    std::map<std::string,std::string> kv;
    size_t i = 0;
    while (i < json.size()) {
        size_t ks = json.find('"',i);
        if (ks==std::string::npos) break;
        size_t ke = json.find('"',ks+1);
        if (ke==std::string::npos) break;
        std::string key = json.substr(ks+1,ke-ks-1);
        size_t colon = json.find(':',ke+1);
        if (colon==std::string::npos) break;
        size_t vs = colon+1;
        while (vs<json.size()&&(json[vs]==' '||json[vs]=='\t')) vs++;
        std::string val;
        if (vs<json.size()&&json[vs]=='"') {
            size_t ve=vs+1;
            while(ve<json.size()){if(json[ve]=='\\'){ve+=2;continue;}if(json[ve]=='"')break;ve++;}
            val=json.substr(vs+1,ve-vs-1); i=ve+1;
        } else {
            size_t ve=vs;
            while(ve<json.size()&&json[ve]!=','&&json[ve]!='}') ve++;
            val=json.substr(vs,ve-vs);
            while(!val.empty()&&(val.back()==' '||val.back()=='}'||val.back()=='\n')) val.pop_back();
            i=ve;
        }
        kv[key]=val;
    }
    return kv;
}

std::string get(const std::map<std::string,std::string>& m,
                const std::string& k, const std::string& d="") {
    auto it=m.find(k); return it!=m.end()?it->second:d;
}
int get_int(const std::map<std::string,std::string>& m, const std::string& k, int d=0) {
    auto it=m.find(k); if(it==m.end()) return d;
    try{return std::stoi(it->second);}catch(...){return d;}
}
std::string esc(const std::string& s) {
    std::string o; for(char c:s){
        if(c=='"') o+="\\\""; else if(c=='\\') o+="\\\\";
        else if(c=='\n') o+="\\n"; else if(c=='\r') o+="\\r";
        else if(c=='\t') o+="\\t"; else o+=c; } return o;
}
std::string ok_r(const std::string& d){return "{\"ok\":true,\"data\":"+d+"}\n";}
std::string er_r(const std::string& m){return "{\"ok\":false,\"error\":\""+esc(m)+"\"}\n";}


std::string handle_page_fault(int page_id, int pid, const std::string& query_hint) {
    std::cout << "[PageFault] page=" << page_id << " PID=" << pid << "\n";
    llmos::PCB* pcb = g_proc_table.get(pid);
    if (pcb) {
        pcb->page_faults++;
        g_proc_table.transition(pid, llmos::ProcessState::WAITING);
    }
    
    std::string exact = g_vector_db.retrieve(page_id);
    if (!exact.empty()) {
        g_page_table.page_in(page_id, exact);
        g_vector_db.remove(page_id);
        if (pcb) g_proc_table.transition(pid, llmos::ProcessState::RUNNING);
        std::cout << "[PageFault] Resolved via exact match.\n";
        return ok_r("{\"status\":\"page_in\",\"page_id\":" + std::to_string(page_id) +
                    ",\"method\":\"exact\",\"content\":\"" + esc(exact) + "\"}");
    }
    
    std::string query = query_hint.empty() ? "page "+std::to_string(page_id) : query_hint;
    auto results = g_vector_db.search(query,3);
    if (!results.empty() && results[0].score >= PAGE_FAULT_SIM_THRESH) {
        auto& best = results[0];
        g_page_table.page_in(best.page_id, best.content);
        g_vector_db.remove(best.page_id);
        if (pcb) g_proc_table.transition(pid, llmos::ProcessState::RUNNING);
        std::cout << "[PageFault] Resolved via cosine sim=" << best.score << "\n";
        return ok_r("{\"status\":\"page_in\",\"page_id\":" + std::to_string(best.page_id) +
                    ",\"method\":\"cosine_search\",\"cosine_sim\":" +
                    std::to_string(best.score) +
                    ",\"content\":\"" + esc(best.content) + "\"}");
    }
    if (pcb) g_proc_table.transition(pid, llmos::ProcessState::READY);
    return er_r("page_fault:not_found:page="+std::to_string(page_id));
}


std::string dispatch(const std::map<std::string,std::string>& p) {
    std::string sc = get(p,"syscall");
    int pid        = get_int(p,"pid",-1);
    std::cout << "[Syscall] " << sc << " (PID=" << pid << ")\n";
    llmos::PCB* pcb = (pid>=0) ? g_proc_table.get(pid) : nullptr;
    if (pcb) pcb->log_syscall(sc);

    
    if (sc=="proc_fork") {
        std::string user=get(p,"username","anon"); int prio=get_int(p,"priority",5);
        int new_pid=g_proc_table.create(user,prio);
        g_proc_table.transition(new_pid,llmos::ProcessState::READY);
        return ok_r("{\"status\":\"forked\",\"pid\":"+std::to_string(new_pid)+"}");
    }
    if (sc=="proc_run")   {g_proc_table.transition(pid,llmos::ProcessState::RUNNING);   return ok_r("{\"status\":\"ok\"}");}
    if (sc=="proc_wait")  {g_proc_table.transition(pid,llmos::ProcessState::WAITING);   return ok_r("{\"status\":\"ok\"}");}
    if (sc=="proc_ready") {g_proc_table.transition(pid,llmos::ProcessState::READY);     return ok_r("{\"status\":\"ok\"}");}
    if (sc=="proc_exit")  {
        g_proc_table.transition(pid,llmos::ProcessState::TERMINATED);
        return ok_r("{\"status\":\"terminated\",\"pid\":"+std::to_string(pid)+"}");
    }
    if (sc=="proc_status") {
        llmos::PCB* pp=g_proc_table.get(pid);
        if (!pp) return er_r("pid_not_found");
        pp->print();
        return ok_r("{\"pid\":"+std::to_string(pp->pid)+
                    ",\"user\":\""+pp->username+"\""+
                    ",\"state\":\""+llmos::state_name(pp->state)+"\""+
                    ",\"priority\":"+std::to_string(pp->priority)+
                    ",\"eff_priority\":"+std::to_string(pp->effective_priority())+
                    ",\"aging_ticks\":"+std::to_string(pp->aging_ticks)+
                    ",\"turns\":"+std::to_string(pp->turn_count)+
                    ",\"page_faults\":"+std::to_string(pp->page_faults)+
                    ",\"pages_swapped\":"+std::to_string(pp->pages_swapped)+"}");
    }

    
    if (sc=="mem_alloc"||sc=="mem_alloc_full") {
        int pgid=get_int(p,"page_id"); std::string cont=get(p,"content");
        
        if (!cont.empty()) g_vector_db.store(pgid, cont);
        int evicted=g_page_table.insert(pgid,cont);
        if (evicted>=0&&pcb) pcb->pages_swapped++;
        return ok_r("{\"status\":\"allocated\",\"evicted_page\":"+std::to_string(evicted)+"}");
    }
    if (sc=="mem_read") {
        int pgid=get_int(p,"page_id"); std::string qh=get(p,"query");
        auto r=g_page_table.access(pgid);
        if (!r) return handle_page_fault(pgid,pid,qh);
        return ok_r("{\"status\":\"hit\",\"page_id\":"+std::to_string(pgid)+
                    ",\"content\":\""+esc(*r)+"\"}");
    }
    if (sc=="mem_free") {
        int pgid=get_int(p,"page_id"); std::string cont=get(p,"content");
        
        if (!cont.empty()) g_vector_db.store(pgid,cont);
        g_page_table.page_out(pgid);
        if (pcb) pcb->pages_swapped++;
        return ok_r("{\"status\":\"paged_out\",\"page_id\":"+std::to_string(pgid)+"}");
    }
    if (sc=="mem_search") {
        std::string q=get(p,"query"); int topk=get_int(p,"top_k",3);
        auto res=g_vector_db.search(q,topk);
        std::string arr="[";
        for(size_t i=0;i<res.size();i++){
            if(i>0) arr+=",";
            arr+="{\"page_id\":"+std::to_string(res[i].page_id)+
                 ",\"score\":"+std::to_string(res[i].score)+
                 ",\"content\":\""+esc(res[i].content)+"\"}";
        }
        arr+="]";
        return ok_r("{\"results\":"+arr+",\"count\":"+std::to_string(res.size())+"}");
    }
    if (sc=="mem_status") {
        return ok_r("{\"ram_used\":"+std::to_string(g_page_table.active_pages())+
                    ",\"ram_capacity\":"+std::to_string(g_page_table.capacity())+
                    ",\"disk_pages\":"+std::to_string(g_vector_db.size())+
                    ",\"policy\":\""+llmos::policy_name(g_page_table.get_policy())+"\"}");
    }

    
    if (sc=="set_policy") {
        std::string pol=get(p,"policy","LRU");
        llmos::ReplacementPolicy rp=llmos::ReplacementPolicy::LRU;
        if(pol=="FIFO")  rp=llmos::ReplacementPolicy::FIFO;
        if(pol=="CLOCK") rp=llmos::ReplacementPolicy::CLOCK;
        if(pol=="LFU")   rp=llmos::ReplacementPolicy::LFU;
        g_page_table.set_policy(rp);
        return ok_r("{\"status\":\"policy_set\",\"policy\":\""+pol+"\"}");
    }

    
    if (sc=="sem_create") {
        std::string name=get(p,"name"); int init=get_int(p,"init_value",1);
        g_sem_mgr.create(name,init);
        return ok_r("{\"status\":\"created\",\"semaphore\":\""+name+"\"}");
    }
    if (sc=="sem_wait") {
        std::string name=get(p,"name");
        bool acquired=g_sem_mgr.wait(name,pid);
        if (!acquired) g_proc_table.transition(pid,llmos::ProcessState::WAITING);
        return ok_r("{\"acquired\":"+std::string(acquired?"true":"false")+
                    ",\"semaphore\":\""+name+"\"}");
    }
    if (sc=="sem_signal") {
        std::string name=get(p,"name"); g_sem_mgr.signal(name,pid);
        return ok_r("{\"status\":\"ok\"}");
    }
    if (sc=="deadlock_check") {
        bool found=g_sem_mgr.check_deadlock();
        return ok_r("{\"deadlock_detected\":"+std::string(found?"true":"false")+"}");
    }
    if (sc=="sem_dump") { g_sem_mgr.dump(); return ok_r("{\"status\":\"ok\"}"); }

    
    if (sc=="fs_read") {
        std::string path=get(p,"path");
        std::ifstream f(path); if(!f) return er_r("file_not_found:"+path);
        std::ostringstream buf; buf<<f.rdbuf();
        std::string cont=buf.str();
        return ok_r("{\"status\":\"ok\",\"path\":\""+esc(path)+
                    "\",\"content\":\""+esc(cont.substr(0,2000))+
                    "\",\"size\":"+std::to_string(cont.size())+"}");
    }
    if (sc=="fs_write") {
        std::string path=get(p,"path"),cont=get(p,"content");
        std::ofstream f(path,std::ios::app); if(!f) return er_r("write_failed:"+path);
        f<<cont;
        return ok_r("{\"status\":\"written\",\"bytes\":"+std::to_string(cont.size())+"}");
    }

    
    if (sc=="kernel_stats") {
        g_page_table.dump(); g_vector_db.dump();
        return ok_r("{\"ram_used\":"+std::to_string(g_page_table.active_pages())+
                    ",\"ram_capacity\":"+std::to_string(g_page_table.capacity())+
                    ",\"disk_pages\":"+std::to_string(g_vector_db.size())+
                    ",\"policy\":\""+llmos::policy_name(g_page_table.get_policy())+"\"}");
    }

    return er_r("unknown_syscall:"+sc);
}


void handle_client(int fd, const std::string& ip) {
    std::cout << "[Kernel] Client connected: " << ip << "\n";
    char buf[8192];
    while (g_running) {
        memset(buf,0,sizeof(buf));
        ssize_t n=recv(fd,buf,sizeof(buf)-1,0);
        if (n<=0) break;
        std::string line(buf,n);
        while(!line.empty()&&(line.back()=='\n'||line.back()=='\r'||line.back()==' '))
            line.pop_back();
        if (line.empty()) continue;
        std::cout << "[Kernel] << " << line.substr(0,120) << "\n";
        std::string response = dispatch(parse_json(line));
        std::cout << "[Kernel] >> " << response.substr(0,120) << "\n";
        send(fd, response.c_str(), response.size(), 0);
    }
    std::cout << "[Kernel] Client disconnected: " << ip << "\n";
    close(fd);
}

void sig_handler(int) {
    std::cout << "\n[Kernel] SIGINT — shutting down...\n";
    g_running = false;
    if (g_scheduler) g_scheduler->stop();
    exit(0);
}


void parse_args(int argc, char* argv[],
                llmos::ReplacementPolicy& policy, int& quantum) {
    for (int i=1; i<argc; i++) {
        std::string arg=argv[i];
        if (arg=="--policy" && i+1<argc) {
            std::string pol=argv[++i];
            if (pol=="FIFO")  policy=llmos::ReplacementPolicy::FIFO;
            if (pol=="CLOCK") policy=llmos::ReplacementPolicy::CLOCK;
            if (pol=="LFU")   policy=llmos::ReplacementPolicy::LFU;
        }
        if (arg=="--quantum" && i+1<argc) {
            try { quantum=std::stoi(argv[++i]); } catch(...) {}
        }
    }
}

int main(int argc, char* argv[]) {
    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);

    llmos::ReplacementPolicy policy = llmos::ReplacementPolicy::LRU;
    int quantum_ms = 500;
    parse_args(argc, argv, policy, quantum_ms);

    
    g_page_table.set_policy(policy);

    std::cout
        << "\n============================================================\n"
        << "  LLM-OS C++ Kernel Server  v3\n"
        << "  RAM frames : " << RAM_FRAMES << "  |  Port: " << PORT << "\n"
        << "  Policy     : " << llmos::policy_name(policy)
        << "  |  Quantum: " << quantum_ms << "ms\n"
        << "  [✓] 4 Replacement Policies (LRU/FIFO/CLOCK/LFU)\n"
        << "  [✓] Priority Scheduling + Aging (anti-starvation)\n"
        << "  [✓] Named Semaphores + Deadlock Detection (RAG)\n"
        << "  [✓] Dirty-bit Write-Back\n"
        << "  [✓] PCB State Machine   [✓] C++ Cosine VectorDB\n"
        << "  [✓] TCP Syscall IPC     [✓] FS Syscalls\n"
        << "============================================================\n\n";

    
    llmos::Scheduler scheduler(g_page_table, g_proc_table, quantum_ms);
    g_scheduler = &scheduler;
    scheduler.start();

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) { std::cerr << "[Kernel] socket() failed\n"; return 1; }
    int opt=1;
    setsockopt(server_fd,SOL_SOCKET,SO_REUSEADDR,&opt,sizeof(opt));
    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port        = htons(PORT);
    if (bind(server_fd,reinterpret_cast<sockaddr*>(&addr),sizeof(addr))<0) {
        std::cerr << "[Kernel] bind() failed — port " << PORT << " in use?\n";
        return 1;
    }
    listen(server_fd,10);
    std::cout << "[Kernel] Ready on port " << PORT << " — waiting for Python AI...\n\n";

    while (g_running) {
        sockaddr_in ca{}; socklen_t cl=sizeof(ca);
        int cfd=accept(server_fd,reinterpret_cast<sockaddr*>(&ca),&cl);
        if (cfd<0) continue;
        std::string ip=inet_ntoa(ca.sin_addr);
        std::thread(handle_client,cfd,ip).detach();
    }
    close(server_fd);
    return 0;
}
