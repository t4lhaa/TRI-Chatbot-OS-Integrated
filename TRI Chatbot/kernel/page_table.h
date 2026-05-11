#pragma once
#include <iostream>
#include <map>
#include <list>
#include <queue>
#include <vector>
#include <string>
#include <chrono>
#include <mutex>
#include <optional>
#include <algorithm>
#include <climits>

namespace llmos {

enum class ReplacementPolicy { LRU, FIFO, CLOCK, LFU };

static std::string policy_name(ReplacementPolicy p) {
    switch (p) {
        case ReplacementPolicy::LRU:   return "LRU";
        case ReplacementPolicy::FIFO:  return "FIFO";
        case ReplacementPolicy::CLOCK: return "CLOCK";
        case ReplacementPolicy::LFU:   return "LFU";
    }
    return "UNKNOWN";
}

struct PageEntry {
    int    page_id    = -1;
    int    frame_id   = -1;
    bool   valid      = false;
    bool   dirty      = false;
    bool   ref_bit    = false;   
    long   last_access = 0;
    int    frequency  = 0;       
    std::string content;

    PageEntry() = default;
    PageEntry(int pid, int fid, const std::string& text)
        : page_id(pid), frame_id(fid), valid(true), dirty(false),
          ref_bit(true), frequency(1), content(text) {
        last_access = static_cast<long>(
            std::chrono::system_clock::now().time_since_epoch().count());
    }
};

class PageTable {
public:
    explicit PageTable(int ram_frames = 10,
                       ReplacementPolicy policy = ReplacementPolicy::LRU)
        : ram_capacity_(ram_frames), next_frame_(0),
          policy_(policy), clock_hand_(0) {
        std::cout << "[PageTable] capacity=" << ram_frames
                  << "  policy=" << policy_name(policy) << "\n";
    }

    
    int insert(int page_id, const std::string& content) {
        std::lock_guard<std::mutex> lock(mtx_);
        if (table_.count(page_id) && table_[page_id].valid) {
            _touch(page_id); table_[page_id].content = content; return -1;
        }
        int evicted = -1;
        if ((int)ring_.size() >= ram_capacity_) evicted = _evict();
        int frame = next_frame_++;
        table_[page_id] = PageEntry(page_id, frame, content);
        ring_.push_back(page_id);
        _policy_insert(page_id);
        return evicted;
    }

    std::optional<std::string> access(int page_id) {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = table_.find(page_id);
        if (it == table_.end() || !it->second.valid) return std::nullopt;
        _touch(page_id);
        return it->second.content;
    }

    void page_out(int page_id) {
        std::lock_guard<std::mutex> lock(mtx_);
        if (table_.count(page_id)) {
            table_[page_id].valid = false; table_[page_id].frame_id = -1;
            _policy_remove(page_id);
            ring_.erase(std::remove(ring_.begin(), ring_.end(), page_id), ring_.end());
        }
    }

    void page_in(int page_id, const std::string& content) { insert(page_id, content); }

    ReplacementPolicy get_policy() const { return policy_; }

    void set_policy(ReplacementPolicy p) {
        std::lock_guard<std::mutex> lock(mtx_);
        policy_ = p; clock_hand_ = 0;
        lru_list_.clear(); lru_pos_.clear();
        while (!fifo_q_.empty()) fifo_q_.pop();
        for (int pid : ring_) {
            if (table_[pid].valid) _policy_insert_nolock(pid);
        }
        std::cout << "[PageTable] Policy -> " << policy_name(p) << "\n";
    }

    void dump() const {
        std::cout << "\n[PageTable] Policy=" << policy_name(policy_)
                  << "  RAM=" << ring_.size() << "/" << ram_capacity_ << "\n";
        for (auto& [pid, e] : table_)
            std::cout << "  pg=" << pid << " valid=" << e.valid
                      << " freq=" << e.frequency << " ref=" << e.ref_bit
                      << " \"" << e.content.substr(0,30) << "\"\n";
    }

    int active_pages() const { return (int)ring_.size(); }
    int capacity()     const { return ram_capacity_; }

private:
    int ram_capacity_, next_frame_;
    ReplacementPolicy policy_;
    std::map<int,PageEntry>                 table_;
    std::vector<int>                        ring_;       
    std::list<int>                          lru_list_;
    std::map<int,std::list<int>::iterator>  lru_pos_;
    std::queue<int>                         fifo_q_;
    int  clock_hand_;
    mutable std::mutex mtx_;

    void _touch(int pid) {
        auto& e = table_[pid];
        e.ref_bit = true; e.frequency++;
        e.last_access = static_cast<long>(
            std::chrono::system_clock::now().time_since_epoch().count());
        if (policy_ == ReplacementPolicy::LRU && lru_pos_.count(pid)) {
            lru_list_.erase(lru_pos_[pid]);
            lru_list_.push_front(pid);
            lru_pos_[pid] = lru_list_.begin();
        }
    }

    void _policy_insert(int pid) { _policy_insert_nolock(pid); }
    void _policy_insert_nolock(int pid) {
        if (policy_ == ReplacementPolicy::LRU) {
            lru_list_.push_front(pid); lru_pos_[pid] = lru_list_.begin();
        } else if (policy_ == ReplacementPolicy::FIFO) {
            fifo_q_.push(pid);
        }
    }

    void _policy_remove(int pid) {
        if (policy_ == ReplacementPolicy::LRU && lru_pos_.count(pid)) {
            lru_list_.erase(lru_pos_[pid]); lru_pos_.erase(pid);
        }
    }

    int _evict() {
        int victim = -1;
        switch (policy_) {
            case ReplacementPolicy::LRU:
                if (!lru_list_.empty()) {
                    victim = lru_list_.back(); lru_list_.pop_back(); lru_pos_.erase(victim);
                } break;
            case ReplacementPolicy::FIFO:
                if (!fifo_q_.empty()) { victim = fifo_q_.front(); fifo_q_.pop(); } break;
            case ReplacementPolicy::CLOCK: {
                int n = (int)ring_.size(), checked = 0;
                while (checked < 2*n) {
                    if (clock_hand_ >= (int)ring_.size()) clock_hand_ = 0;
                    int pid = ring_[clock_hand_];
                    if (!table_[pid].valid) { clock_hand_++; checked++; continue; }
                    if (!table_[pid].ref_bit) { victim = pid; clock_hand_++; break; }
                    table_[pid].ref_bit = false; clock_hand_++; checked++;
                }
                if (victim < 0 && !ring_.empty()) victim = ring_.front();
            } break;
            case ReplacementPolicy::LFU: {
                int min_f = INT_MAX; long oldest = LONG_MAX;
                for (auto& [pid,e] : table_) {
                    if (!e.valid) continue;
                    if (e.frequency < min_f || (e.frequency == min_f && e.last_access < oldest))
                    { min_f = e.frequency; oldest = e.last_access; victim = pid; }
                }
            } break;
        }
        if (victim >= 0) {
            table_[victim].valid = false; table_[victim].frame_id = -1; table_[victim].dirty = true;
            ring_.erase(std::remove(ring_.begin(),ring_.end(),victim),ring_.end());
            std::cout << "[" << policy_name(policy_) << "] Evict page " << victim << "\n";
        }
        return victim;
    }
};
} 
