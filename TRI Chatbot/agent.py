from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import time
from functools import lru_cache
from typing import Generator

import chromadb
import requests
import wikipedia
from duckduckgo_search import DDGS
from openai import OpenAI
from sentence_transformers import SentenceTransformer


import os
from dotenv import load_dotenv


load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
WEATHER_API_KEY    = os.getenv("WEATHER_API_KEY")
NEWS_API_KEY       = os.getenv("NEWS_API_KEY")
EXCHANGE_API_KEY   = os.getenv("EXCHANGE_API_KEY")

MODEL                = "openai/gpt-4o-mini" 
EMBED_MODEL          = "all-MiniLM-L6-v2"
CHROMA_PATH          = "./agent_memory"
MAX_STEPS            = 10
MAX_ACTIVE_TURNS     = 10
SIMILARITY_THRESHOLD = 0.45

openrouter_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": "https://github.com/your-repo",
        "X-Title":      "ReAct-RAG-Agent",
    },
)

embedder = SentenceTransformer(EMBED_MODEL)

db = chromadb.PersistentClient(path=CHROMA_PATH)

col = db.get_or_create_collection(
    "agent_memory",
    metadata={"hnsw:space": "cosine"},
)


def get_user_collection(username: str | None):
    """Return the ChromaDB collection scoped to a specific user.
    Falls back to the global collection when username is None."""
    if not username:
        return col
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", username).lower()
    cname = f"user_{safe}_memory"
    return db.get_or_create_collection(
        cname,
        metadata={"hnsw:space": "cosine"},
    )

def cosine_similarity(a: list, b: list) -> float:
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)

TOOL_SCHEMAS: list = [
    {"type": "function", "function": {"name": "calculator",
        "description": "Safely evaluate a mathematical expression.",
        "parameters": {"type": "object",
            "properties": {"expression": {"type": "string", "description": "Math expression, e.g. '3**2 + 10'"}},
            "required": ["expression"]}}},
    {"type": "function", "function": {"name": "web_search",
        "description": "Search the web using DuckDuckGo.",
        "parameters": {"type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 3}},
            "required": ["query"]}}},
    {"type": "function", "function": {"name": "wikipedia_search",
        "description": "Retrieve a Wikipedia summary for a topic. REQUIRED param: 'topic' (string).",
        "parameters": {"type": "object",
            "properties": {"topic": {"type": "string", "description": "The subject to look up on Wikipedia"}},
            "required": ["topic"]}}},
    {"type": "function", "function": {"name": "get_weather",
        "description": "Get current weather for a city.",
        "parameters": {"type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"]}}},
    {"type": "function", "function": {"name": "get_news",
        "description": "Fetch latest news articles on a topic. REQUIRED param: 'topic' (string).",
        "parameters": {"type": "object",
            "properties": {"topic": {"type": "string", "description": "The news subject to search for"},
                           "max_articles": {"type": "integer", "default": 3}},
            "required": ["topic"]}}},
    {"type": "function", "function": {"name": "get_country_info",
        "description": "Get facts about a country. REQUIRED param: 'name' (string, the country name).",
        "parameters": {"type": "object",
            "properties": {"name": {"type": "string", "description": "The country name, e.g. 'France'"}},
            "required": ["name"]}}},
    {"type": "function", "function": {"name": "convert_currency",
        "description": "Convert an amount between currencies.",
        "parameters": {"type": "object",
            "properties": {"amount": {"type": "number"}, "from_currency": {"type": "string"}, "to_currency": {"type": "string"}},
            "required": ["amount", "from_currency", "to_currency"]}}},
    {"type": "function", "function": {"name": "define_word",
        "description": "Get the English definition of a word.",
        "parameters": {"type": "object",
            "properties": {"word": {"type": "string"}},
            "required": ["word"]}}},
    {"type": "function", "function": {"name": "read_file",
        "description": "Read a local file (text, code, CSV, JSON, etc.).",
        "parameters": {"type": "object",
            "properties": {"filepath": {"type": "string"}},
            "required": ["filepath"]}}},
    {"type": "function", "function": {"name": "retrieve_memory",
        "description": "Retrieve semantically similar past context from ChromaDB.",
        "parameters": {"type": "object",
            "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 3}},
            "required": ["query"]}}},
    {"type": "function", "function": {"name": "save_to_memory",
        "description": "Save important information to long-term vector memory.",
        "parameters": {"type": "object",
            "properties": {"text": {"type": "string"}, "source": {"type": "string", "default": "agent"}},
            "required": ["text"]}}},
]


def calculator(expression: str) -> dict:
    allowed = set("0123456789+-*/(). **%")
    if not all(c in allowed for c in expression):
        return {"error": "Invalid characters in expression."}
    try:
        result = eval(expression, {"__builtins__": {}})
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": str(e)}


def web_search(query: str, max_results: int = 3) -> dict:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return {"results": [{"title": r["title"], "snippet": r["body"], "url": r["href"]} for r in results]}
    except Exception as e:
        return {"error": str(e)}


def wikipedia_search(topic: str) -> dict:
    try:
        summary = wikipedia.summary(topic, sentences=4, auto_suggest=False)
        return {"topic": topic, "summary": summary}
    except wikipedia.DisambiguationError as e:
        return {"error": f"Ambiguous topic. Try one of: {e.options[:3]}"}
    except wikipedia.PageError:
        return {"error": f"No Wikipedia page found for '{topic}'."}
    except Exception as e:
        return {"error": str(e)}


@lru_cache(maxsize=50)
def get_weather(city: str) -> dict:
    try:
        resp = requests.get("https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": WEATHER_API_KEY, "units": "metric"}, timeout=5)
        d = resp.json()
        if resp.status_code != 200:
            return {"error": d.get("message", "Weather API error.")}
        return {"city": d["name"], "temperature": f"{d['main']['temp']}C",
                "feels_like": f"{d['main']['feels_like']}C",
                "condition": d["weather"][0]["description"],
                "humidity": f"{d['main']['humidity']}%",
                "wind_speed": f"{d['wind']['speed']} m/s"}
    except Exception as e:
        return {"error": str(e)}


@lru_cache(maxsize=50)
def get_news(topic: str, max_articles: int = 3) -> dict:
    try:
        resp = requests.get("https://newsapi.org/v2/everything",
            params={"q": topic, "pageSize": max_articles, "sortBy": "publishedAt", "apiKey": NEWS_API_KEY}, timeout=5)
        articles = resp.json().get("articles", [])
        return {"articles": [{"title": a["title"], "source": a["source"]["name"],
                               "summary": a.get("description", ""), "url": a["url"]} for a in articles]}
    except Exception as e:
        return {"error": str(e)}


def get_country_info(name: str) -> dict:
    try:
        resp = requests.get(f"https://restcountries.com/v3.1/name/{name}", timeout=5)
        c = resp.json()[0]
        return {"country": c["name"]["common"], "capital": c.get("capital", ["N/A"])[0],
                "population": c.get("population"), "region": c.get("region"),
                "currencies": list(c.get("currencies", {}).keys()),
                "languages": list(c.get("languages", {}).values())}
    except Exception as e:
        return {"error": str(e)}


@lru_cache(maxsize=50)
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    try:
        resp = requests.get(
            f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/pair/{from_currency}/{to_currency}/{amount}",
            timeout=5)
        d = resp.json()
        if d.get("result") != "success":
            return {"error": d.get("error-type", "Currency API error.")}
        return {"from": from_currency, "to": to_currency, "amount": amount,
                "converted": d["conversion_result"], "rate": d["conversion_rate"]}
    except Exception as e:
        return {"error": str(e)}


def define_word(word: str) -> dict:
    try:
        resp = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=5)
        data = resp.json()[0]
        defs = []
        for m in data.get("meanings", [])[:2]:
            for d in m.get("definitions", [])[:1]:
                defs.append({"part_of_speech": m["partOfSpeech"],
                             "definition": d["definition"], "example": d.get("example", "N/A")})
        return {"word": word, "phonetic": data.get("phonetic", ""), "definitions": defs}
    except Exception as e:
        return {"error": str(e)}


def read_file(filepath: str) -> dict:
    """Read a local text/code file. Binary docs (PDF/DOCX/XLSX) should be uploaded via the UI."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"filepath": filepath, "content": content[:4000], "truncated": len(content) > 4000}
    except Exception as e:
        return {"error": str(e)}


def retrieve_memory(query: str, top_k: int = 3, username: str | None = None) -> dict:
    user_col = get_user_collection(username)
    if user_col.count() == 0:
        return {"relevant_chunks": [], "similarity_scores": []}
    q_vec   = embedder.encode([query])[0].tolist()
    results = user_col.query(query_embeddings=[q_vec], n_results=min(top_k, user_col.count()),
                             include=["documents", "distances", "metadatas", "embeddings"])
    chunks = []
    for doc, dist, meta, emb in zip(results["documents"][0], results["distances"][0],
                                     results["metadatas"][0], results["embeddings"][0]):
        chroma_score   = round(1 - dist, 4)
        explicit_score = round(cosine_similarity(q_vec, emb), 4)
        if chroma_score >= SIMILARITY_THRESHOLD:
            chunks.append({"text": doc, "cosine_similarity": explicit_score,
                           "score": chroma_score, "meta": meta})
    return {"relevant_chunks": chunks, "similarity_threshold": SIMILARITY_THRESHOLD, "embed_model": EMBED_MODEL}


def save_to_memory(text: str, source: str = "agent", username: str | None = None) -> dict:
    if not text.strip():
        return {"status": "skipped"}
    user_col = get_user_collection(username)
    vector = embedder.encode([text])[0].tolist()
    doc_id = hashlib.md5((text + (username or "")).encode()).hexdigest()
    try:
        user_col.add(ids=[doc_id], embeddings=[vector], documents=[text],
                     metadatas=[{"source": source, "timestamp": str(time.time()),
                                 "user": username or "global"}])
        return {"status": "saved", "id": doc_id, "source": source}
    except Exception:
        return {"status": "duplicate", "id": doc_id}


def get_memory_count(username: str | None = None) -> int:
    return get_user_collection(username).count()


def get_memory_samples(limit: int = 5, username: str | None = None) -> list:
    user_col = get_user_collection(username)
    count = user_col.count()
    if count == 0:
        return []
    try:
        raw = user_col.get(limit=min(limit, count), include=["documents", "metadatas"])
        return list(zip(raw["documents"], raw["metadatas"]))
    except Exception:
        return []


TOOLS: dict = {
    "calculator": calculator, "web_search": web_search,
    "wikipedia_search": wikipedia_search, "get_weather": get_weather,
    "get_news": get_news, "get_country_info": get_country_info,
    "convert_currency": convert_currency, "define_word": define_word,
    "read_file": read_file, "retrieve_memory": retrieve_memory,
    "save_to_memory": save_to_memory,
}

TOOL_DESCRIPTIONS = """
Available tools — use EXACT parameter names as listed:
- calculator(expression)                               : Safe math eval
- web_search(query, max_results=3)                     : DuckDuckGo web search
- wikipedia_search(topic)                              : Wikipedia summary — param is "topic", NOT "query"
- get_weather(city)                                    : Live weather for a city
- get_news(topic, max_articles=3)                      : Latest news — param is "topic", NOT "query"
- get_country_info(name)                               : Country facts — param is "name", NOT "country"
- convert_currency(amount, from_currency, to_currency) : Currency conversion
- define_word(word)                                    : English word definition
- read_file(filepath)                                  : Read a local text/code file
- retrieve_memory(query, top_k=3)                      : Cosine-similarity vector search
- save_to_memory(text, source)                         : Save info to ChromaDB memory

CRITICAL: Always use the exact parameter names above. Examples:
  wikipedia_search → {"topic": "Barack Obama"}   ✓   {"query": "Barack Obama"}   ✗
  get_news         → {"topic": "AI news"}        ✓   {"query": "AI news"}        ✗
  get_country_info → {"name": "France"}          ✓   {"country": "France"}       ✗
"""

SYSTEM_PROMPT = """You are TRI Chatbot - an autonomous AI agent using the ReAct framework.

PIPELINE (follow for every request):
  Step 1 - UNDERSTAND  : Analyse the user intent.
  Step 2 - REASON      : Write a Thought about which tool(s) you need.
  Step 3 - ACT         : Call the tool using exact format below.
  Step 4 - OBSERVE     : Read the Observation returned.
  Step 5 - SYNTHESISE  : Combine all observations into a Final Answer.

OUTPUT FORMAT:
Thought: [your reasoning]
Action: [tool_name]
Action Input: {"param": "value"}

After each Observation, write another Thought or end with:
Final Answer: [complete, clear response]

RULES:
- Always write a Thought before every Action.
- Use tools for facts - never hallucinate.
- Chain multiple tools when needed.
- If a tool errors, try another approach.
- Final Answer must be complete and well-formatted.
- ALWAYS use the exact parameter names as defined in the tool descriptions.
- When the user uploads a document (PDF, Word, Excel, code file), the extracted
  content is already injected into the prompt — analyse it directly without
  calling read_file unless the user mentions a separate local path.
"""

PARAM_ALIASES: dict = {
    "wikipedia_search": {"query": "topic", "search": "topic", "term": "topic", "subject": "topic"},
    "get_news":         {"query": "topic", "search": "topic", "term": "topic", "subject": "topic", "keyword": "topic"},
    "get_country_info": {"country": "name", "country_name": "name", "nation": "name"},
    "get_weather":      {"location": "city", "place": "city", "town": "city"},
    "define_word":      {"term": "word", "query": "word"},
}

def repair_params(tool_name: str, tool_input: dict) -> dict:
    aliases = PARAM_ALIASES.get(tool_name, {})
    if not aliases:
        return tool_input
    return {aliases.get(k, k): v for k, v in tool_input.items()}


def format_memory_block(chunks: list) -> str:
    if not chunks:
        return ""
    block = "\n--- Relevant memory (retrieved via cosine similarity) ---\n"
    for c in chunks:
        sim = c.get("cosine_similarity", c.get("score", "?"))
        block += f"[cosine_sim={sim}] {c['text']}\n"
    return block + "--- End of memory ---\n"


def manage_context(chat_history: list, username: str | None = None) -> list:
    if len(chat_history) <= MAX_ACTIVE_TURNS:
        return chat_history
    old    = chat_history[:-MAX_ACTIVE_TURNS]
    recent = chat_history[-MAX_ACTIVE_TURNS:]
    for i in range(0, len(old) - 1, 2):
        u = old[i].get("content", "")
        if isinstance(u, list):
            u = " ".join(p.get("text", "") for p in u if isinstance(p, dict) and p.get("type") == "text")
        a = old[i + 1].get("content", "") if i + 1 < len(old) else ""
        save_to_memory(f"Past exchange - User: {u[:300]} | Agent: {a[:300]}",
                       source="offloaded_turn", username=username)
    return recent


def save_exchange(question: str, answer: str, observations: list,
                  username: str | None = None) -> None:
    save_to_memory(f"Q: {question}\nA: {answer}", source="qa_pair", username=username)
    for obs in observations:
        if len(obs) > 40:
            save_to_memory(obs, source="tool_result", username=username)


_DOC_TYPE_LABELS: dict = {
    ".pdf":  "PDF document",
    ".docx": "Word document", ".doc": "Word document",
    ".xlsx": "Excel spreadsheet", ".xls": "Excel spreadsheet",
    ".pptx": "PowerPoint presentation",
    ".c": "C source file", ".h": "C header file",
    ".cpp": "C++ source file", ".cc": "C++ source file",
    ".cxx": "C++ source file", ".hpp": "C++ header file",
    ".cs":  "C# source file",
    ".py":  "Python script",
    ".js":  "JavaScript file", ".ts":  "TypeScript file",
    ".java": "Java source file",
    ".rs":  "Rust source file",
    ".go":  "Go source file",
    ".rb":  "Ruby script",
    ".sh":  "Shell script", ".bash": "Bash script",
    ".sql": "SQL script",
    ".html": "HTML file", ".css": "CSS stylesheet",
    ".json": "JSON file", ".yaml": "YAML file", ".yml": "YAML file",
    ".csv":  "CSV data file",
    ".md":   "Markdown document",
    ".txt":  "text file",
    ".xml":  "XML file",
}

def _doc_label(filename: str, file_context: dict) -> str:
    if file_context.get("doc_type"):
        return file_context["doc_type"]
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _DOC_TYPE_LABELS.get(ext, "uploaded file")


def _build_user_message(user_input: str, file_context: dict | None) -> dict:
    if not file_context:
        return {"role": "user", "content": user_input or "Hello"}

    ftype    = file_context.get("type")
    fname    = file_context.get("filename", "uploaded file")
    doc_label = _doc_label(fname, file_context)

    if ftype == "text":
        content    = file_context.get("content", "")
        truncated  = file_context.get("truncated", False)
        trunc_note = "\n[... file truncated — only the first portion is shown ...]" if truncated else ""

        if user_input:
            combined = (
                f"The user has uploaded a {doc_label}: **{fname}**\n\n"
                f"Extracted contents:\n```\n{content}{trunc_note}\n```\n\n"
                f"User's question / instruction: {user_input}"
            )
        else:
            combined = (
                f"The user has uploaded a {doc_label}: **{fname}**\n\n"
                f"Extracted contents:\n```\n{content}{trunc_note}\n```\n\n"
                "Please analyse this file thoroughly and summarise its key contents, "
                "structure, and any notable details."
            )
        return {"role": "user", "content": combined}

    elif ftype == "image":
        b64       = file_context.get("base64", "")
        mime_type = file_context.get("mime_type", "image/jpeg")
        text_part = user_input if user_input else "Please describe and analyse this image in detail."
        content = [
            {"type": "image_url",
             "image_url": {"url": f"data:{mime_type};base64,{b64}", "detail": "high"}},
            {"type": "text", "text": text_part},
        ]
        return {"role": "user", "content": content}

    return {"role": "user", "content": user_input or "Hello"}


def call_openrouter(system_prompt: str, messages: list,
                    stop_at_observation: bool = True) -> str:
    formatted = []
    for msg in messages:
        role = "assistant" if msg["role"] == "model" else msg["role"]
        formatted.append({"role": role, "content": msg["content"]})

    full_messages  = [{"role": "system", "content": system_prompt}] + formatted
    stop_sequences = ["Observation:"] if stop_at_observation else []
    max_retries    = 4
    base_delay     = 2.0

    for attempt in range(max_retries):
        try:
            response = openrouter_client.chat.completions.create(
                model=MODEL,
                messages=full_messages,
                temperature=0.2,
                max_tokens=2048,
                stop=stop_sequences if stop_sequences else None,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            error_msg = str(e)
            if any(code in error_msg for code in ("429", "503", "502")):
                if attempt < max_retries - 1:
                    sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0, 1)
                    print(f"\n  [!] Rate-limited. Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    continue
            return (
                "Thought: Persistent server issues.\n"
                "Final Answer: The AI server is experiencing high demand. Please try again in a moment."
            )

    return (
        "Thought: All retries exhausted.\n"
        "Final Answer: Unable to reach the server. Please try again shortly."
    )



def parse_llm_output(text: str) -> dict:
    if "Final Answer:" in text:
        return {"type": "final", "content": text.split("Final Answer:")[-1].strip()}

    action_match = re.search(r"Action:\s*(\w+)", text)
    input_match  = re.search(r"Action Input:\s*(\{.*?\})", text, re.DOTALL | re.IGNORECASE)

    if action_match and input_match:
        raw_json = input_match.group(1)
        try:
            tool_input = json.loads(raw_json)
        except json.JSONDecodeError:
            raw_json = re.sub(r"'", '"', raw_json)
            raw_json = re.sub(r",\s*}", "}", raw_json)
            try:
                tool_input = json.loads(raw_json)
            except json.JSONDecodeError:
                tool_input = {}

        tool_name  = action_match.group(1).strip()
        tool_input = repair_params(tool_name, tool_input)

        schema_match = next((s for s in TOOL_SCHEMAS if s["function"]["name"] == tool_name), None)
        if schema_match:
            required = schema_match["function"]["parameters"].get("required", [])
            missing  = [r for r in required if r not in tool_input]
            if missing:
                correction = (
                    f"Observation: {{\"error\": \"Wrong parameter names for {tool_name}. "
                    f"Missing required: {missing}. "
                    f"Use exact names — wikipedia_search needs 'topic', "
                    f"get_news needs 'topic', get_country_info needs 'name'\"}}"
                )
                return {"type": "llm_correction", "content": correction}

        return {"type": "action", "tool": tool_name, "input": tool_input}

    return {"type": "unknown", "content": text}


def run_tool(tool_name: str, tool_input: dict, username: str | None = None) -> str:
    if tool_name not in TOOLS:
        obs = {"error": f"Tool '{tool_name}' not found. Available: {list(TOOLS.keys())}"}
    else:
        try:
            if tool_name in ("retrieve_memory", "save_to_memory"):
                obs = TOOLS[tool_name](**tool_input, username=username)
            else:
                obs = TOOLS[tool_name](**tool_input)
        except TypeError as e:
            obs = {"error": f"Wrong parameters for '{tool_name}': {e}"}
        except Exception as e:
            obs = {"error": f"Tool failed: {e}"}
    return f"Observation: {json.dumps(obs, indent=2)}"



def run_react_loop(system_prompt: str, conversation: list,
                   username: str | None = None) -> dict:
    observations: list = []
    tool_calls:   list = []
    messages = list(conversation)

    for step in range(MAX_STEPS):
        print(f"\n  [Step {step + 1}]", end=" ", flush=True)
        llm_output = call_openrouter(system_prompt, messages, stop_at_observation=True)
        messages.append({"role": "model", "content": llm_output})
        parsed = parse_llm_output(llm_output)

        if parsed["type"] == "final":
            print("Done.")
            clean = re.sub(r'\n{3,}', '\n\n', parsed["content"]).strip()
            return {"answer": clean, "steps": step + 1, "tool_calls": tool_calls,
                    "observations": observations, "status": "success"}

        if parsed["type"] == "action":
            tname, tinput = parsed["tool"], parsed["input"]
            print(f"-> {tname}({tinput})")
            obs_str = run_tool(tname, tinput, username=username)
            observations.append(obs_str)
            tool_calls.append({"tool": tname, "input": tinput})
            messages.append({"role": "user", "content": obs_str})
        elif parsed["type"] == "llm_correction":
            print("-> param correction, retrying...")
            messages.append({"role": "user", "content": parsed["content"]})
        elif parsed["type"] == "error":
            messages.append({"role": "user", "content": parsed["content"]})
        else:
            messages.append({"role": "user", "content": "Please use exact Thought / Action / Final Answer format."})

    return {"answer": "Reached step limit. Please rephrase your question.",
            "steps": MAX_STEPS, "tool_calls": tool_calls,
            "observations": observations, "status": "max_steps_reached"}


def run_react_loop_streaming(system_prompt: str, conversation: list,
                             username: str | None = None) -> Generator:
    observations: list = []
    tool_calls:   list = []
    messages = list(conversation)

    for step in range(MAX_STEPS):
        yield {"event": "step", "data": {"step": step + 1}}
        llm_output = call_openrouter(system_prompt, messages, stop_at_observation=True)
        messages.append({"role": "model", "content": llm_output})
        parsed = parse_llm_output(llm_output)

        if parsed["type"] == "final":
            clean = re.sub(r'\n{3,}', '\n\n', parsed["content"]).strip()
            yield {"event": "final", "data": {"answer": clean, "steps": step + 1,
                                               "tool_calls": tool_calls, "status": "success"}}
            return

        if parsed["type"] == "action":
            tname, tinput = parsed["tool"], parsed["input"]
            yield {"event": "tool_call", "data": {"tool": tname, "input": tinput}}
            obs_str = run_tool(tname, tinput, username=username)
            observations.append(obs_str)
            tool_calls.append({"tool": tname, "input": tinput})
            messages.append({"role": "user", "content": obs_str})
            yield {"event": "observation", "data": {"result": obs_str[:300]}}
        elif parsed["type"] == "llm_correction":
            yield {"event": "thought", "data": {"text": "Correcting tool parameters, retrying…"}}
            messages.append({"role": "user", "content": parsed["content"]})
        elif parsed["type"] == "error":
            messages.append({"role": "user", "content": parsed["content"]})
            yield {"event": "thought", "data": {"text": parsed["content"]}}
        else:
            messages.append({"role": "user", "content": "Use exact Thought / Action / Final Answer format."})

    yield {"event": "final", "data": {"answer": "Reached step limit. Please rephrase.",
                                       "steps": MAX_STEPS, "tool_calls": tool_calls,
                                       "status": "max_steps_reached"}}



def agent(user_input: str, chat_history: list,
          file_context: dict | None = None,
          username: str | None = None) -> dict:
    print(f"\n[Agent] Query: {user_input[:80]}... (user={username})")
    if file_context:
        print(f"[Agent] File: {file_context.get('filename')} ({file_context.get('type')})")

    mem_query = user_input or (file_context or {}).get("filename", "file upload")
    memories  = retrieve_memory(mem_query, top_k=3, username=username)
    rag_block = format_memory_block(memories["relevant_chunks"])
    print(f"[Agent] RAG: {len(memories['relevant_chunks'])} chunk(s) retrieved")

    chat_history  = manage_context(chat_history, username=username)
    system_prompt = SYSTEM_PROMPT + rag_block + TOOL_DESCRIPTIONS
    user_msg      = _build_user_message(user_input, file_context)
    conversation  = list(chat_history) + [user_msg]
    result        = run_react_loop(system_prompt, conversation, username=username)

    save_exchange(user_input, result["answer"], result["observations"], username=username)
    hist_content  = user_input or f"[uploaded {(file_context or {}).get('filename', 'file')}]"
    chat_history.append({"role": "user",  "content": hist_content})
    chat_history.append({"role": "model", "content": result["answer"]})
    return result


def agent_streaming(user_input: str, chat_history: list,
                    file_context: dict | None = None,
                    username: str | None = None) -> Generator:
    """Streaming version of agent() — for the /stream SSE endpoint."""
    if file_context:
        print(f"[Agent] File: {file_context.get('filename')} ({file_context.get('type')})")

    mem_query = user_input or (file_context or {}).get("filename", "file upload")
    memories  = retrieve_memory(mem_query, top_k=3, username=username)
    rag_block = format_memory_block(memories["relevant_chunks"])
    chat_history  = manage_context(chat_history, username=username)
    system_prompt = SYSTEM_PROMPT + rag_block + TOOL_DESCRIPTIONS
    user_msg      = _build_user_message(user_input, file_context)
    conversation  = list(chat_history) + [user_msg]

    final_answer = ""
    for event in run_react_loop_streaming(system_prompt, conversation, username=username):
        yield event
        if event["event"] == "final":
            final_answer = event["data"].get("answer", "")

    if final_answer:
        save_exchange(user_input, final_answer, [], username=username)
        hist_content = user_input or f"[uploaded {(file_context or {}).get('filename', 'file')}]"
        chat_history.append({"role": "user",  "content": hist_content})
        chat_history.append({"role": "model", "content": final_answer})


def print_banner():
    print("\n" + "=" * 62)
    print(f"  TRI Chatbot  |  ReAct + RAG  |  {MODEL}")
    print("  'memory' = inspect DB   |   'exit' = quit")
    print("=" * 62)


def inspect_memory(username: str | None = None):
    user_col = get_user_collection(username)
    count = user_col.count()
    print(f"\n  ChromaDB: {count} chunk(s) stored (user={username}).")
    if count > 0:
        sample = user_col.get(limit=3, include=["documents", "metadatas"])
        for doc, meta in zip(sample["documents"], sample["metadatas"]):
            print(f"  [{meta.get('source','?')}] {doc[:100]}...")


def main():
    print_banner()
    chat_history: list = []
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break
        if user_input.lower() == "memory":
            inspect_memory()
            continue

        print("\nAgent thinking...", end="", flush=True)
        start = time.time()
        try:
            result = agent(user_input, chat_history)
        except Exception as e:
            print(f"\n  Error: {e}")
            continue

        elapsed = round(time.time() - start, 1)
        print(f"\n\nAgent: {result['answer']}")
        print(f"\n  [{result['steps']} step(s) | {len(result['tool_calls'])} tool(s) | {elapsed}s]")
        if result["tool_calls"]:
            print("  Tools: " + ", ".join(t["tool"] for t in result["tool_calls"]))


if __name__ == "__main__":
    main()