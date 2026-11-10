from evals.run import grade, numbers_in, tools_match, value_matches


def result(**overrides) -> dict:
    return {"answer": "", "citations": 0, "tools": [], "insufficient": False} | overrides


def test_numbers_are_parsed_and_citation_markers_ignored():
    assert numbers_in("About 83,716 reviews at 2.43 stars [1].") == [83716.0, 2.43]


def test_citation_number_cannot_pass_as_the_answer():
    assert not value_matches(1, "The answer is unclear [1].", 0)


def test_value_tolerance():
    assert value_matches(2.43, "It is 2.44", 0.01)
    assert not value_matches(2.43, "It is 2.50", 0.01)


def test_text_answers_match_ignoring_case():
    assert value_matches("March", "Lowest in MARCH of that year", 0)


def test_tools_match_any_acceptable_set():
    assert tools_match({"run_sql", "search_reviews"}, [["get_theme_trends"], ["run_sql"]])
    assert not tools_match({"search_reviews"}, [["run_sql"]])


def test_numeric_question_needs_every_value():
    question = {"tolerance": 0.01, "expected_tools": [["run_sql"]]}
    good = result(answer="Ratings were 2.78 and 2.09.", tools=["run_sql"])
    bad = result(answer="Ratings were 2.78.", tools=["run_sql"])
    assert grade(question, good, [2.78, 2.09]) == {"correct": True, "router_correct": True}
    assert grade(question, bad, [2.78, 2.09])["correct"] is False


def test_refusal_must_be_flagged_and_has_no_router_score():
    question = {"must_refuse": True}
    assert grade(question, result(answer="No data.", insufficient=True), None) == {
        "correct": True,
        "router_correct": None,
    }
    assert grade(question, result(answer="$13B."), None)["correct"] is False


def test_citation_required_when_asked_for():
    question = {"needs_citation": True, "expected_tools": [["search_reviews"]]}
    answer = result(answer="Ads.", tools=["search_reviews"])
    assert grade(question, answer, None)["correct"] is False
    assert grade(question, answer | {"citations": 1}, None)["correct"] is True


def test_failed_request_is_never_correct():
    question = {"expected_tools": [["run_sql"]]}
    assert grade(question, result(answer="x", error="HTTP 500"), None)["correct"] is False
