import copy

from trivia import questions, state

GOOD = {"question": "Which planet has the most moons?", "options": ["Jupiter", "Saturn", "Uranus", "Neptune"], "answer_index": 1,
        "fun_fact": "Saturn has more than 140 confirmed moons."}


def bad(**kw):
    q = copy.deepcopy(GOOD)
    q.update(kw)
    return q


def test_valid_question():
    assert questions.validate_question(GOOD) is None


def test_invalid_questions():
    assert questions.validate_question({"question": "x"}) == "missing fields"
    assert questions.validate_question(bad(question="No question mark here at all")) == "bad question text"
    assert questions.validate_question(bad(options=["A", "B", "C"])) == "need 4 short options"
    assert questions.validate_question(bad(options=["Mars", "mars", "Venus", "Earth"])) == "duplicate options"
    assert questions.validate_question(bad(options=["Mars", "Venus", "Earth", "x" * 40])) == "need 4 short options"
    assert questions.validate_question(bad(answer_index=4)) == "bad answer_index"
    assert questions.validate_question(bad(answer_index=True)) == "bad answer_index"
    assert questions.validate_question(bad(fun_fact="short")) == "bad fun_fact"
    assert questions.validate_question(bad(options=["H2O", "CO2", "x^2", "NaCl"])) == "not speakable"


def test_schema_and_validator_agree_on_limits():
    props = questions.QUESTION_SCHEMA["properties"]
    assert props["question"]["maxLength"] == questions.Q_MAX
    assert props["options"]["items"]["maxLength"] == questions.OPT_MAX
    assert set(questions.QUESTION_SCHEMA["required"]) == set(GOOD)


def test_duplicate_rejection():
    history = [{"topic": "Space", "q": "Which planet has the most moons?"}]
    assert state.is_duplicate("Which planet has the MOST moons ?", "Movies", history)  # exact after normalizing, any topic
    assert state.is_duplicate("Which planet has the most moon?", "Space", history)  # near-identical, same topic
    assert not state.is_duplicate("Which planet is closest to the Sun?", "Space", history)


def test_balance_answers_keeps_correct_answer():
    qs = [copy.deepcopy(GOOD) for _ in range(8)]
    out = questions.balance_answers(qs, "seed")
    for q in out:
        assert q["options"][q["answer_index"]] == "Saturn"
        assert sorted(q["options"]) == sorted(GOOD["options"])
    assert len({q["answer_index"] for q in out}) >= 3  # spread over A-D


def test_balance_answers_sorts_numbers():
    q = bad(options=["1969", "1957", "1972", "1961"], answer_index=0)
    out = questions.balance_answers([q], "s")[0]
    assert out["options"] == ["1957", "1961", "1969", "1972"] and out["answer_index"] == 2


def test_caption(cfg):
    c = questions.caption(cfg, "Space", 8)
    assert c.startswith("Can you score 8/8") and "comment your score" in c.lower()
    assert f"@{cfg['account_handle']}" in c  # reconcile marker
    assert 8 <= c.count("#") <= 10 and len(c) < 2200


def test_topic_rotation_is_lru(cfg):
    topics = list(cfg["topics"])
    assert state.pick_topic(cfg, {}) == topics[0]
    rotation = {t: "2026-11-10" for t in topics}
    rotation[topics[3]] = "2026-11-01"
    assert state.pick_topic(cfg, rotation) == topics[3]
