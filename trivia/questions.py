"""Question generation + fact-check via `claude -p` (subscription auth via CLAUDE_CODE_OAUTH_TOKEN), plus caption."""
import json
import random
import re
import subprocess
import tempfile
import time

from . import state

Q_MAX, OPT_MAX, FACT_MAX = 100, 28, 100
SPEAKABLE = re.compile(r"^[\w\s'’&.,:!?()\-/]+$")

QUESTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["question", "options", "answer_index", "fun_fact"],
    "properties": {
        "question": {"type": "string", "minLength": 10, "maxLength": Q_MAX},
        "options": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "string", "minLength": 1, "maxLength": OPT_MAX}},
        "answer_index": {"type": "integer", "minimum": 0, "maximum": 3},
        "fun_fact": {"type": "string", "minLength": 10, "maxLength": FACT_MAX},
    },
}
GEN_SCHEMA = {
    "type": "object",
    "required": ["questions"],
    "properties": {"questions": {"type": "array", "minItems": 8, "maxItems": 20, "items": QUESTION_SCHEMA}},
}
CHECK_SCHEMA = {
    "type": "object",
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "keep", "correct_index", "reason"],
                "properties": {
                    "id": {"type": "integer"},
                    "keep": {"type": "boolean"},
                    "correct_index": {"type": "integer", "minimum": -1, "maximum": 3},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

SYSTEM = "You write and verify trivia for a family-friendly Instagram quiz. Reply only through the structured output."

GEN_PROMPT = """Write {count} multiple-choice trivia questions on the topic "{topic}" for a narrated quiz video.

Rules:
- Evergreen, verifiable facts only. Nothing that changes over time: no current records, "current"/"latest"/"as of", recent events, living people's ages, prices, rankings, populations or statistics that drift.
- No politics, religion, wars-as-controversy, tragedies, or other sensitive or contentious subjects. No song lyrics or quotes from copyrighted works.
- Exactly one option is unambiguously correct; the other three are plausible but clearly wrong.
- Everything is read aloud by a text-to-speech voice: plain words, no symbols, formulas, abbreviations, roman numerals, or long numbers. Options are 1-4 words.
- "question": one clear sentence ending with "?", max {qmax} characters.
- "options": 4 distinct short answers, max {omax} characters each, no "all/none of the above".
- "answer_index": 0-3, index of the correct option.
- "fun_fact": one surprising, true sentence related to the answer, max {fmax} characters, not repeating the question.
- Mix difficulty: about a third easy, a third medium, a third hard. Vary sub-themes within the topic.
{avoid}"""

CHECK_PROMPT = """Fact-check these trivia questions on "{topic}" with great care. For each id return:
- correct_index: the index (0-3) of the option that is actually correct, or -1 if none or more than one is correct.
- keep: false if ANY of these apply: the marked answer is wrong or debatable; more than one option could be argued correct; the fun fact is false, unverifiable or misleading; it depends on time-sensitive facts; it touches politics, religion or other contentious subjects; it quotes song lyrics or other copyrighted text; the question or options would sound awkward or confusing when read aloud by a text-to-speech voice. Otherwise true.
- reason: a few words.

Questions:
{items}"""


def validate_question(q: dict) -> str | None:
    """Return an error string, or None if the question is well-formed."""
    try:
        text, opts, ans, fact = q["question"], q["options"], q["answer_index"], q["fun_fact"]
    except (KeyError, TypeError):
        return "missing fields"
    if not (isinstance(text, str) and 10 <= len(text) <= Q_MAX and text.strip().endswith("?")):
        return "bad question text"
    if not (isinstance(opts, list) and len(opts) == 4 and all(isinstance(o, str) and 0 < len(o.strip()) <= OPT_MAX for o in opts)):
        return "need 4 short options"
    if len({o.strip().lower() for o in opts}) != 4:
        return "duplicate options"
    if not (isinstance(ans, int) and not isinstance(ans, bool) and 0 <= ans <= 3):
        return "bad answer_index"
    if not (isinstance(fact, str) and 10 <= len(fact) <= FACT_MAX):
        return "bad fun_fact"
    if any("\n" in s for s in [text, fact, *opts]) or not all(SPEAKABLE.match(o) for o in opts):
        return "not speakable"
    return None


def claude_json(prompt: str, schema: dict, model: str, fallback: str | None, timeout: int = 600) -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(schema),
           "--model", model, "--system-prompt", SYSTEM, "--tools", "", "--no-session-persistence",
           "--setting-sources", "project"]
    if fallback and fallback != model:
        cmd += ["--fallback-model", fallback]
    # Empty temp cwd: no project files or settings leak into the prompt.
    with tempfile.TemporaryDirectory() as cwd:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"claude exited {res.returncode}: {(res.stderr or res.stdout).strip()[-400:]}")
    data = json.loads(res.stdout)
    if data.get("is_error") or "structured_output" not in data:
        raise RuntimeError(f"claude returned no structured output: {str(data.get('result'))[:400]}")
    return data["structured_output"]


def balance_answers(questions: list[dict], seed: str) -> list[dict]:
    """Spread correct answers evenly over A-D (LLMs favour B/C). Numeric options are sorted ascending instead."""
    rng = random.Random(seed)
    positions = [0, 1, 2, 3] * (len(questions) // 4 + 1)
    rng.shuffle(positions)
    out = []
    for q, pos in zip(questions, positions):
        opts, ans = list(q["options"]), q["options"][q["answer_index"]]
        try:
            opts.sort(key=lambda o: float(o.replace(",", "")))
        except ValueError:
            others = [o for o in opts if o != ans]
            rng.shuffle(others)
            opts = others[:pos] + [ans] + others[pos:]
        out.append({**q, "options": opts, "answer_index": opts.index(ans)})
    return out


def get_questions(cfg: dict, topic: str, history: list[dict], seed: str, log=print) -> list[dict]:
    qc, cc = cfg["questions"], cfg["claude"]
    kept: list[dict] = []
    recent = [h["q"] for h in history if h["topic"] == topic][-80:]
    for attempt in range(1, cc["attempts"] + 1):
        try:
            avoid = recent + [q["question"] for q in kept]
            avoid_txt = ("Do NOT reuse or closely paraphrase these earlier questions:\n- " + "\n- ".join(avoid)) if avoid else ""
            gen = claude_json(
                GEN_PROMPT.format(count=qc["candidates"], topic=topic, qmax=Q_MAX, omax=OPT_MAX, fmax=FACT_MAX, avoid=avoid_txt),
                GEN_SCHEMA, cc["generate_model"], cc.get("fallback_model"),
            )["questions"]
            fresh = []
            for q in gen:
                err = validate_question(q)
                if err:
                    log(f"  rejected (invalid: {err}): {q.get('question')!r}")
                elif state.is_duplicate(q["question"], topic, history + [{"topic": topic, "q": k["question"]} for k in kept + fresh]):
                    log(f"  rejected (duplicate): {q['question']!r}")
                else:
                    fresh.append(q)
            if fresh:
                items = "\n".join(
                    json.dumps({"id": i, "question": q["question"], "options": q["options"], "answer_index": q["answer_index"], "fun_fact": q["fun_fact"]}, ensure_ascii=False)
                    for i, q in enumerate(fresh)
                )
                verdicts = {v["id"]: v for v in claude_json(CHECK_PROMPT.format(topic=topic, items=items), CHECK_SCHEMA, cc["factcheck_model"], cc.get("fallback_model"))["verdicts"]}
                for i, q in enumerate(fresh):
                    v = verdicts.get(i)
                    if v and v["keep"] and v["correct_index"] == q["answer_index"]:
                        kept.append(q)
                    else:
                        log(f"  fact-check dropped: {q['question']!r} ({v['reason'] if v else 'no verdict'})")
            log(f"  attempt {attempt}: {len(kept)} questions kept")
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
            log(f"  attempt {attempt} failed: {e}")
            time.sleep(10 * attempt)
        if len(kept) >= qc["target"]:
            break
    if len(kept) < qc["min"]:
        raise RuntimeError(f"only {len(kept)} questions survived validation + fact-check (need {qc['min']})")
    return balance_answers(kept[: qc["target"]], seed)


def caption(cfg: dict, topic: str, n: int) -> str:
    t = re.sub(r"[^a-z0-9]", "", topic.lower())
    tags = list(dict.fromkeys([f"{t}trivia", f"{t}quiz", *cfg["hashtags_common"]]))[:10]
    return (
        f"Can you score {n}/{n} on this {topic} quiz?\n\n"
        f"Play along, then comment your score below!\n"
        f"Follow @{cfg['account_handle']} for daily trivia.\n\n" + " ".join(f"#{x}" for x in tags)
    )
