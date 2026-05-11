#pragma once

#include <iostream>
#include <vector>
#include <string>
#include <map>
#include <cmath>
#include <algorithm>
#include <sstream>
#include <mutex>
#include <thread>
#include <functional>

namespace llmos {



class TextEmbedder {
public:
    
    void fit(const std::string& text) {
        std::lock_guard<std::mutex> lock(mtx_);
        for (auto& w : tokenize(text)) {
            if (!vocab_.count(w)) {
                vocab_[w] = static_cast<int>(vocab_.size());
            }
        }
    }

    
    std::vector<float> embed(const std::string& text) {
        std::lock_guard<std::mutex> lock(mtx_);
        if (vocab_.empty()) return {};

        std::vector<float> vec(vocab_.size(), 0.0f);
        auto words = tokenize(text);
        for (auto& w : words) {
            auto it = vocab_.find(w);
            if (it != vocab_.end())
                vec[it->second] += 1.0f;
        }
        
        float norm = 0.0f;
        for (float v : vec) norm += v * v;
        norm = std::sqrt(norm);
        if (norm > 1e-9f) {
            for (float& v : vec) v /= norm;
        }
        return vec;
    }

    int vocab_size() const { return static_cast<int>(vocab_.size()); }

private:
    std::map<std::string, int> vocab_;
    mutable std::mutex mtx_;

    std::vector<std::string> tokenize(const std::string& text) {
        std::vector<std::string> tokens;
        std::istringstream ss(text);
        std::string word;
        while (ss >> word) {
            
            std::string clean;
            for (char c : word) {
                if (std::isalpha(c)) clean += std::tolower(c);
            }
            if (clean.size() > 1) tokens.push_back(clean);
        }
        return tokens;
    }
};


inline float cosine_similarity(const std::vector<float>& a,
                                const std::vector<float>& b) {
    if (a.size() != b.size() || a.empty()) return 0.0f;
    float dot = 0.0f, mag_a = 0.0f, mag_b = 0.0f;
    for (size_t i = 0; i < a.size(); i++) {
        dot   += a[i] * b[i];
        mag_a += a[i] * a[i];
        mag_b += b[i] * b[i];
    }
    mag_a = std::sqrt(mag_a);
    mag_b = std::sqrt(mag_b);
    if (mag_a < 1e-9f || mag_b < 1e-9f) return 0.0f;
    return dot / (mag_a * mag_b);
}


struct DiskPage {
    int                  page_id;
    std::string          content;
    std::vector<float>   embedding;
    long                 stored_at;
};


class VectorDB {
public:
    
    void store(int page_id, const std::string& content) {
        std::lock_guard<std::mutex> lock(mtx_);
        embedder_.fit(content);
        DiskPage dp;
        dp.page_id   = page_id;
        dp.content   = content;
        dp.embedding = embedder_.embed(content);
        dp.stored_at = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        
        pages_.erase(
            std::remove_if(pages_.begin(), pages_.end(),
                [page_id](const DiskPage& p){ return p.page_id == page_id; }),
            pages_.end());
        pages_.push_back(dp);
        std::cout << "[VectorDB] Stored page " << page_id
                  << " on disk (" << pages_.size() << " total)\n";
    }

    
    
    struct SearchResult {
        int         page_id;
        std::string content;
        float       score;
    };

    std::vector<SearchResult> search(const std::string& query, int top_k = 3) {
        std::lock_guard<std::mutex> lock(mtx_);
        if (pages_.empty()) return {};

        embedder_.fit(query);
        auto q_vec = embedder_.embed(query);

        std::vector<std::pair<float, int>> scores;
        for (size_t i = 0; i < pages_.size(); i++) {
            
            auto p_vec = embedder_.embed(pages_[i].content);
            
            if (p_vec.size() < q_vec.size()) p_vec.resize(q_vec.size(), 0.0f);
            if (q_vec.size() < p_vec.size()) {
                q_vec.resize(p_vec.size(), 0.0f);
            }
            float sim = cosine_similarity(q_vec, p_vec);
            scores.push_back({sim, static_cast<int>(i)});
        }

        std::sort(scores.begin(), scores.end(),
                  [](auto& a, auto& b){ return a.first > b.first; });

        std::vector<SearchResult> results;
        int k = std::min(top_k, static_cast<int>(scores.size()));
        for (int i = 0; i < k; i++) {
            auto& dp = pages_[scores[i].second];
            results.push_back({dp.page_id, dp.content, scores[i].first});
            std::cout << "[VectorDB] Page-In candidate: page=" << dp.page_id
                      << " cosine_sim=" << scores[i].first << "\n";
        }
        return results;
    }

    
    std::string retrieve(int page_id) {
        std::lock_guard<std::mutex> lock(mtx_);
        for (auto& dp : pages_) {
            if (dp.page_id == page_id) return dp.content;
        }
        return "";
    }

    
    void remove(int page_id) {
        std::lock_guard<std::mutex> lock(mtx_);
        pages_.erase(
            std::remove_if(pages_.begin(), pages_.end(),
                [page_id](const DiskPage& p){ return p.page_id == page_id; }),
            pages_.end());
    }

    int size() const {
        std::lock_guard<std::mutex> lock(mtx_);
        return static_cast<int>(pages_.size());
    }

    void dump() const {
        std::lock_guard<std::mutex> lock(mtx_);
        std::cout << "\n[VectorDB] " << pages_.size() << " page(s) on disk:\n";
        for (auto& dp : pages_) {
            std::cout << "  page=" << dp.page_id
                      << " embed_dim=" << dp.embedding.size()
                      << " content=\"" << dp.content.substr(0, 50) << "\"\n";
        }
    }

private:
    std::vector<DiskPage> pages_;
    TextEmbedder          embedder_;
    mutable std::mutex    mtx_;
};

} 
