import json
import re
import logging
import requests
from config import APIMART_API_KEY, AI_MODEL, APIMART_BASE_URL

logger = logging.getLogger(__name__)


def estimate_words_per_page(pages: int) -> int:
    """Estimate total words for an N-page IEEE paper.
    ~480 words/page target. The AI tends to underproduce so we go higher
    than the conservative 380 used previously.
    """
    return pages * 480


def call_api(messages: list, max_tokens: int = 8000) -> str:
    """
    Make a direct HTTP POST to the apimart.ai OpenAI-compatible endpoint.
    Returns the assistant message content as a string.
    """
    url = APIMART_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {APIMART_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "stream": False,
    }

    logger.info(f"Calling API: {url} with model {AI_MODEL}")
    resp = requests.post(url, headers=headers, json=payload, timeout=120)

    logger.info(f"API response status: {resp.status_code}")
    logger.info(f"API raw response (first 300 chars): {repr(resp.text[:300])}")

    if resp.status_code != 200:
        raise ValueError(f"API error {resp.status_code}: {resp.text[:500]}")

    if not resp.text or not resp.text.strip():
        raise ValueError(
            f"API returned empty response body (status 200). "
            f"This usually means the request was too large or the model is unavailable. "
            f"Model: {AI_MODEL}"
        )

    data = resp.json()
    logger.info(f"API response keys: {list(data.keys())}")

    # Handle standard OpenAI format
    if "choices" in data:
        content = data["choices"][0]["message"]["content"]
        if not content or not content.strip():
            raise ValueError("API returned empty content in choices[0].message.content")
        return content.strip()

    # Some APIs return {"content": "..."} directly
    if "content" in data:
        return data["content"].strip()

    # Handle error responses that come with 200 status
    if "error" in data:
        raise ValueError(f"API error in response: {data['error']}")

    # Fallback: dump the whole response for debugging
    raise ValueError(f"Unexpected API response format: {json.dumps(data)[:500]}")


def generate_paper_content(title: str, pages: int, author_name: str = "Author",
                           author_affil: str = "University",
                           anti_detection: bool = False) -> dict:
    """
    Call the AI API in two passes to generate a full IEEE research paper.
    Split into two calls to avoid max_token truncation on large papers.
    anti_detection: if True, injects humanization rules into the system prompt
    to reduce AI detection scores (GPTZero, Turnitin, etc).
    """
    # IEEE two-column A4 at 10pt Times Roman holds ~900 words of body text per page.
    # We add ~15% buffer since the AI under-produces relative to targets.
    total_words = pages * 900

    # Number of references scales with paper length
    n_refs = max(8, pages + 4)

    # Word budgets per section (must sum to ~total_words)
    w_abstract = 130
    w_intro    = int(total_words * 0.17)
    w_rw       = int(total_words * 0.19)
    w_method   = int(total_words * 0.22)
    w_impl     = int(total_words * 0.17)
    w_res      = int(total_words * 0.15)
    w_conc     = int(total_words * 0.10)

    # Paragraph counts (aim for 4-5 sentences each, ~80 words/paragraph)
    p_intro  = max(3, w_intro  // 80)
    p_rw     = max(3, w_rw     // 80)
    p_method = max(3, w_method // 80)
    p_impl   = max(3, w_impl   // 80)
    p_res    = max(3, w_res    // 80)
    p_conc   = max(2, w_conc   // 80)

    prompt1 = f"""You are writing Part 1 of a {pages}-page IEEE conference paper. Output ONLY valid JSON.

Title: "{title}"

CRITICAL REQUIREMENTS:
- Each section MUST reach its exact word count. Write verbosely with full sentences.
- Do NOT summarize or truncate. Expand every point with detail, examples, and analysis.
- No backslashes, no LaTeX, no markdown fences.

Return ONLY this JSON (no extra text):
{{
  "title": "{title}",
  "abstract": "<exactly {w_abstract} words: problem statement, proposed approach, key results, significance>",
  "keywords": ["<kw1>", "<kw2>", "<kw3>", "<kw4>", "<kw5>"],
  "introduction": {{
    "title": "I. INTRODUCTION",
    "content": "<write exactly {p_intro} substantial paragraphs (~{w_intro} words total). Cover: research background and context, problem statement and motivation, existing gaps, proposed solution overview, paper structure outline. Each paragraph must be 4-5 full sentences.>"
  }},
  "related_work": {{
    "title": "II. RELATED WORK",
    "content": "<write exactly {p_rw} substantial paragraphs (~{w_rw} words total). Survey existing literature with [1],[2] style citations. Cover at least 3 sub-topics. Compare and contrast approaches. Each paragraph must be 4-5 full sentences.>"
  }},
  "methodology": {{
    "title": "III. METHODOLOGY",
    "content": "<write exactly {p_method} substantial paragraphs (~{w_method} words total). Describe the proposed system architecture, algorithms, and components in detail. Include one EQUATION: formula_expression (1). Each paragraph must be 4-5 full sentences.>"
  }}
}}"""

    # --- CALL 2: second half of paper ---
    refs_list = "\n    ".join(f'"[{i}] <author(s)>, <title in double quotes>, <journal/conf>, <year>"'
                               for i in range(1, n_refs + 1))

    prompt2 = f"""You are writing Part 2 of a {pages}-page IEEE conference paper. Output ONLY valid JSON.

Title: "{title}"

CRITICAL REQUIREMENTS:
- Each section MUST reach its exact word count. Write verbosely with full sentences.
- Do NOT summarize or truncate. Include concrete numbers, system details, and analysis.
- No backslashes, no LaTeX, no markdown fences.

Return ONLY this JSON (no extra text):
{{
  "implementation": {{
    "title": "IV. IMPLEMENTATION",
    "content": "<write exactly {p_impl} substantial paragraphs (~{w_impl} words total). Describe hardware/software setup, datasets used (with statistics), training/evaluation procedures, tools and frameworks. Each paragraph must be 4-5 full sentences.>"
  }},
  "results": {{
    "title": "V. RESULTS AND DISCUSSION",
    "content": "<write exactly {p_res} substantial paragraphs (~{w_res} words total). Present quantitative results from Table I, compare against baselines, analyze performance gains with specific percentages, discuss failure cases and limitations. Each paragraph must be 4-5 full sentences. Do NOT reference figures.>"
  }},
  "conclusion": {{
    "title": "VI. CONCLUSION AND FUTURE WORK",
    "content": "<write exactly {p_conc} substantial paragraphs (~{w_conc} words total). Summarize contributions, state limitations clearly, propose concrete future directions. Each paragraph must be 4-5 full sentences.>"
  }},
  "table": {{
    "caption": "TABLE I: Performance Comparison of Methods",
    "headers": ["Method", "Accuracy (%)", "Precision (%)", "Recall (%)", "F1-Score (%)"],
    "rows": [
      ["Baseline A", "84.2", "83.5", "83.1", "83.3"],
      ["Baseline B", "88.7", "87.9", "87.4", "87.6"],
      ["Proposed Method", "95.3", "94.8", "94.5", "94.6"]
    ]
  }},
  "references": [
    {refs_list}
  ]
}}"""

    humanize_rules = (
        " HUMANIZATION RULES (apply to ALL text):"
        " 1) Vary sentence length drastically — mix very short sentences (5-8 words) with longer ones (25-35 words)."
        " 2) Occasionally start sentences with conjunctions: But, And, Yet, So, However."
        " 3) Include rhetorical questions naturally, e.g. Why does this matter? or What does this mean in practice?"
        " 4) Add hedging language: arguably, one might suggest, it appears that, in many cases."
        " 5) Use active voice more than passive. Write confidently, not neutrally."
        " 6) Vary paragraph length: some 2-sentence, some 5-sentence paragraphs."
        " 7) Avoid starting consecutive sentences with the same word."
        " 8) Use synonyms instead of repeating keywords."
    ) if anti_detection else ""

    sys_msg = {
        "role": "system",
        "content": (
            "You are an expert IEEE research paper writer producing publication-ready content. "
            "You MUST write VERBOSE, DETAILED academic text that reaches the exact word count specified. "
            "Do not cut corners or summarize. Each section must be substantive and thorough. "
            "Always respond with valid JSON only. No markdown fences, no extra text. "
            "CRITICAL: Do NOT use backslash characters inside any JSON string values. "
            "Do NOT use LaTeX notation. Write math as plain text. "
            "Do NOT use apostrophes or smart quotes inside JSON strings."
            + humanize_rules
        )
    }

    logger.info("Generating paper part 1...")
    raw1 = call_api([sys_msg, {"role": "user", "content": prompt1}], max_tokens=16000)
    raw1 = re.sub(r"^```(?:json)?\s*", "", raw1.strip())
    raw1 = re.sub(r"\s*```$", "", raw1)

    logger.info("Generating paper part 2...")
    raw2 = call_api([sys_msg, {"role": "user", "content": prompt2}], max_tokens=16000)
    raw2 = re.sub(r"^```(?:json)?\s*", "", raw2.strip())
    raw2 = re.sub(r"\s*```$", "", raw2)

    def sanitize_json(raw: str) -> str:
        """
        Robust JSON sanitizer:
        1. Strips invalid control characters (except \\n, \\r, \\t).
        2. Escapes literal newlines/tabs inside strings (fixes 'Invalid control character').
        3. Fixes invalid escape sequences (like \\_ or \\' or \\LaTeX).
        """
        # 1. Strip binary control characters (0-31) except 9(TAB), 10(LF), 13(CR)
        raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)

        # 2. State machine to escape valid control chars (\\n, \\t) ONLY inside strings
        #    and handle backslash logic
        res = []
        in_string = False
        i = 0
        length = len(raw)
        
        while i < length:
            char = raw[i]
            
            # Check for quote (toggle string state)
            if char == '"':
                # Determine if this quote is escaped by counting preceding backslashes
                bs_count = 0
                j = i - 1
                while j >= 0 and raw[j] == '\\':
                    bs_count += 1
                    j -= 1
                
                # If even backslashes, it's a real quote (unescaped)
                if bs_count % 2 == 0:
                    in_string = not in_string
                res.append(char)
            
            elif char == '\n':
                if in_string: res.append('\\n')
                else:         res.append(char)  # keep structural newline
                
            elif char == '\t':
                if in_string: res.append('\\t')
                else:         res.append(char)  # keep structural tab
                
            elif char == '\r':
                if not in_string: res.append(char) # skip CR inside strings
                
            elif char == '\\':
                # 3. Handle backslashes
                # If followed by a valid JSON escape char, keep it.
                # If followed by invalid (like space, single quote, etc), double it.
                if i + 1 < length:
                    next_char = raw[i+1]
                    if next_char in '"\\/bfnrtu':
                        res.append(char) # valid start of escape
                    else:
                        res.append('\\\\') # invalid escape start -> escape the backslash
                else:
                    res.append('\\\\') # trailing backslash
            
            else:
                res.append(char)
                
            i += 1
            
        return "".join(res)

    def parse_json_safe(raw: str, label: str) -> dict:
        """3-tier JSON parse: direct → sanitized → brace-extract+sanitized."""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        sanitized = sanitize_json(raw)
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError:
            pass
    def repair_truncated_json(raw: str) -> str:
        """Attempt to close truncated JSON strings or objects."""
        raw = raw.strip()
        # If text ends inside a string (odd number of unescaped quotes), close it
        # This is a naive heuristic but works for most 'cut off mid-sentence' cases
        quote_count = len(re.findall(r'(?<!\\)"', raw))
        if quote_count % 2 != 0:
            raw += '"'
        
        # Close open braces/brackets
        open_braces = raw.count('{') - raw.count('}')
        open_brackets = raw.count('[') - raw.count(']')
        raw += '}' * open_braces
        raw += ']' * open_brackets
        return raw

    def parse_json_safe(raw: str, label: str) -> dict:
        """3-tier JSON parse: direct → sanitized → repaired → brace-extract."""
        # 1. Try direct
        try: return json.loads(raw)
        except json.JSONDecodeError: pass

        # 2. Try sanitizing escapes
        sanitized = sanitize_json(raw)
        try: return json.loads(sanitized)
        except json.JSONDecodeError: pass

        # 3. Try repairing truncation on the sanitized version
        repaired = repair_truncated_json(sanitized)
        try: return json.loads(repaired)
        except json.JSONDecodeError: pass

        # 4. Try extracting the largest brace block
        match = re.search(r'\{.*\}', repaired, re.DOTALL)
        if match:
            try: return json.loads(match.group())
            except json.JSONDecodeError: pass
        
        # 5. Last ditch: try repair on the extracted block
        if match:
             try: return json.loads(repair_truncated_json(match.group()))
             except json.JSONDecodeError as e:
                 raise ValueError(f"{label} JSON parse failed: {e}\nRaw: {sanitized[:500]}")

        raise ValueError(f"{label} JSON parse failed — no JSON found.\nRaw: {raw[:400]}")

    part1 = parse_json_safe(raw1, "Part 1")
    part2 = parse_json_safe(raw2, "Part 2")

    # Merge both parts; inject a placeholder authors list
    # (bot.py always overrides this with real user data)
    paper_data = {**part1, **part2}
    if "authors" not in paper_data:
        paper_data["authors"] = [{"name": author_name, "department": "Engineering",
                                   "university": author_affil, "city": "India",
                                   "email": f"{author_name.lower().replace(' ', '.')}@university.edu"}]
    return paper_data
