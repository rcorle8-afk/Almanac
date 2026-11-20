import base64
import io
import json
from types import SimpleNamespace

import pytest

from server.engine.models import Question
from server.questions.validate import check_bank, servable
from server.questions.verify import (
    FALLBACK_BETA,
    MODELS,
    SUBMIT_TOOL,
    Finding,
    Source,
    Usage,
    apply_verdict,
    calculate,
    check_supporting,
    domain_of,
    evaluate,
    fetch_page,
    log_run,
    normalize,
    numbers_in,
    page_key,
    page_text,
    pdf_text,
    research,
    research_prompt,
    run,
    save_bank,
    select,
)

QUESTION = {
    "id": "tower",
    "text": "How tall is the tower?",
    "unit": "metres",
    "answer": 330,
    "tick": 1,
    "source_url": "https://example.com",
    "source_note": "",
    "category": "places",
    "difficulty": 1,
    "as_of": "2026",
    "status": "unverified",
}
QUOTE_A = "The tower stands 330 metres tall."
QUOTE_B = "Its height is 1,083 ft (330 m) to the tip."
URL_A = "https://www.towers.gov/facts"
URL_B = "https://en.wikipedia.org/wiki/Tower"
PAGES = {
    URL_A: normalize(f"Welcome. {QUOTE_A} Visit us."),
    URL_B: normalize(f"History. {QUOTE_B} Later."),
}


def source(url=URL_A, quote=QUOTE_A, stated=330.0, value=330.0):
    return Source(url=url, quote=quote, value_as_stated=stated, value_in_question_unit=value)


def finding(*sources, ambiguous=False, changing=False):
    return Finding(
        sources=list(sources) or [source(), source(URL_B, QUOTE_B)],
        ambiguous=ambiguous,
        changes_within_a_year=changing,
        notes="note",
    )


def verdict(found, pages=PAGES, question=QUESTION):
    return evaluate(question, found, pages.get)


class TestGates:
    def test_two_independent_confirmed_sources_pass(self):
        result = verdict(finding())
        assert result.status == "agent_verified"
        assert result.reasons == []

    def test_no_finding_needs_review(self):
        assert verdict(None).status == "needs_review"

    def test_an_invented_quote_counts_for_nothing(self):
        fake = source(quote="The tower stands 330 metres, experts agree.")
        result = verdict(finding(fake))
        assert result.status == "needs_review"
        assert "quote not found" in result.notes[0]

    def test_a_failed_extra_source_is_noted_without_blocking(self):
        fake = source(quote="The tower stands 330 metres, experts agree.")
        result = verdict(finding(fake, source(URL_B, QUOTE_B)))
        assert result.status == "agent_verified"
        assert "quote not found" in result.notes[0]

    def test_an_unreadable_page_is_noted_without_blocking(self):
        result = verdict(finding(source("https://blocked.org/x"), source(URL_B, QUOTE_B)))
        assert result.status == "agent_verified"
        assert any("could not read" in note for note in result.notes)

    def test_a_quote_must_state_its_claimed_number(self):
        wrong = source(stated=500.0, value=330.0)
        result = verdict(finding(wrong))
        assert result.status == "needs_review"
        assert any("does not state" in note for note in result.notes)

    def test_one_confirmed_source_is_enough(self):
        assert verdict(finding(source())).status == "agent_verified"

    def test_disagreeing_sources_are_disputed(self):
        high = source(URL_B, "Its height is 400 m.", 400.0, 400.0)
        pages = {**PAGES, URL_B: normalize("Its height is 400 m.")}
        result = verdict(finding(source(), high), pages)
        assert result.status == "disputed"
        assert any("disagree" in reason for reason in result.reasons)

    def test_an_unconfirmed_source_can_still_raise_a_dispute(self):
        conflict = source("https://blocked.org/x", "Height 400 m.", 400.0, 400.0)
        result = verdict(finding(source(), source(URL_B, QUOTE_B), conflict))
        assert result.status == "disputed"

    def test_sources_that_contradict_the_bank_are_disputed(self):
        question = {**QUESTION, "answer": 250}
        result = verdict(finding(), question=question)
        assert result.status == "disputed"
        assert result.reasons == ["sources say 330.0, the bank says 250"]

    @pytest.mark.parametrize("answer", [331, 300, 360])
    def test_estimates_within_ten_percent_pass(self, answer):
        question = {**QUESTION, "answer": answer}
        assert verdict(finding(), question=question).status == "agent_verified"

    def test_ambiguity_flag_needs_review(self):
        assert verdict(finding(ambiguous=True)).status == "needs_review"

    def test_unstable_answers_need_review(self):
        assert verdict(finding(changing=True)).status == "needs_review"

    def test_unit_conversion_is_allowed_when_the_page_states_the_number(self):
        quote = "The mean distance is 384,400 km."
        url = "https://moon.gov/a"
        question = {**QUESTION, "answer": 384.4, "unit": "thousand km"}
        pages = {url: normalize(quote), URL_B: normalize("It is 384,400 km away.")}
        found = finding(
            source(url, quote, 384400.0, 384.4),
            source(URL_B, "It is 384,400 km away.", 384400.0, 384.4),
        )
        assert verdict(found, pages, question).status == "agent_verified"


SETUP_URL = "https://www.towers.gov/build"
SETUP_QUOTE = "Construction took 2 years and 2 months."
HINT_URL = "https://en.wikipedia.org/wiki/Liberty"
HINT_QUOTE = "The statue is 93 metres from ground to torch."
CASE = {
    **QUESTION,
    "kind": "case",
    "context": "The tower went up in just over 2 years.",
    "context_source_url": SETUP_URL,
    "context_source_quote": SETUP_QUOTE,
    "hint_text": "The Statue of Liberty is 93 metres tall, torch included.",
    "hint_source_url": HINT_URL,
    "hint_source_quote": HINT_QUOTE,
}
CASE_PAGES = {**PAGES, SETUP_URL: normalize(SETUP_QUOTE), HINT_URL: normalize(f"Facts. {HINT_QUOTE}")}


class TestCaseGates:
    def test_a_case_passes_when_its_setup_and_hint_are_on_their_pages(self):
        result = verdict(finding(), CASE_PAGES, CASE)
        assert (result.status, result.reasons) == ("agent_verified", [])

    def test_a_plain_question_has_nothing_extra_to_check(self):
        assert check_supporting(QUESTION, {}.get) == []

    def test_a_hint_whose_page_cannot_be_read_needs_review(self):
        pages = {url: text for url, text in CASE_PAGES.items() if url != HINT_URL}
        result = verdict(finding(), pages, CASE)
        assert result.status == "needs_review"
        assert result.reasons == [f"could not read the hint's source: {HINT_URL}"]

    def test_a_setup_quote_that_is_not_on_the_page_needs_review(self):
        question = {**CASE, "context_source_quote": "Construction took 5 years."}
        result = verdict(finding(), CASE_PAGES, question)
        assert result.reasons == [f"the setup's quote was not found on {SETUP_URL}"]

    def test_a_quote_must_state_a_figure_the_hint_uses(self):
        question = {**CASE, "hint_text": "The Statue of Liberty is 150 metres tall."}
        result = verdict(finding(), CASE_PAGES, question)
        assert result.reasons == ["the hint's quote does not state a figure the hint uses"]

    def test_a_hint_must_not_give_the_answer_away(self):
        quote = "The tower stands 330 metres tall."
        question = {**CASE, "hint_text": "It stands 330 metres tall.", "hint_source_url": URL_A, "hint_source_quote": quote}
        assert verdict(finding(), CASE_PAGES, question).reasons == ["the hint states the answer"]

    def test_the_answer_written_out_in_full_is_still_the_answer(self):
        quote = "It drew 1,300,000 visitors."
        question = {
            **CASE,
            "answer": 1.3,
            "unit": "million visitors",
            "hint_text": "It drew 1,300,000 visitors.",
            "hint_source_url": URL_A,
            "hint_source_quote": quote,
        }
        pages = {**CASE_PAGES, URL_A: normalize(quote)}
        assert "the hint states the answer" in check_supporting(question, pages.get)

    def test_the_agent_reads_the_setup_and_opens_both_pages_but_never_sees_the_hint(self):
        prompt = research_prompt(CASE)
        assert CASE["context"] in prompt
        assert SETUP_URL in prompt and HINT_URL in prompt
        assert CASE["hint_text"] not in prompt and HINT_QUOTE not in prompt
        assert "330" not in prompt

    def test_a_plain_question_s_prompt_is_unchanged(self):
        assert research_prompt(QUESTION) == (
            "Question: How tall is the tower?\nUnit: metres\nFind the answer and call submit_finding."
        )


SOUND_URL = "https://physics.gov/sound"
SOUND_QUOTE = "In dry air at 20 C, sound travels at 343 m/s."
EQUATOR_QUESTION = {**QUESTION, "id": "sound", "unit": "hours", "answer": 32.45}


def calculated(expression="40075 / (343 * 3.6)", url=SOUND_URL, extra=()):
    found = Finding(
        sources=[source(url, SOUND_QUOTE, 343.0, 343.0).model_copy(update={"role": "input"}), *extra],
        ambiguous=False,
        changes_within_a_year=False,
        notes="",
        calculation=expression,
    )
    return found


class TestCalculations:
    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("40075 / (343 * 3.6)", 32.455),
            ("40,075 / (343 × 3.6)", 32.455),
            ("384400 / 5 / 24", 3203.33),
            ("2 ** 10", 1024),
        ],
    )
    def test_plain_arithmetic_is_evaluated(self, expression, expected):
        assert calculate(expression) == pytest.approx(expected, rel=1e-4)

    @pytest.mark.parametrize(
        "expression",
        ["__import__('os').system('x')", "2 ** 1000", "1 / 0", "5 - 10", "len('abc')", "", "3 +"],
    )
    def test_anything_else_is_refused(self, expression):
        assert calculate(expression) is None

    def test_a_calculation_with_a_confirmed_input_passes(self):
        pages = {SOUND_URL: normalize(f"Facts. {SOUND_QUOTE}")}
        result = evaluate(EQUATOR_QUESTION, calculated(), pages.get)
        assert result.status == "agent_verified"

    def test_a_calculation_needs_a_confirmed_input(self):
        result = evaluate(EQUATOR_QUESTION, calculated(), {}.get)
        assert result.status == "needs_review"

    def test_a_calculation_that_misses_the_bank_is_disputed(self):
        pages = {SOUND_URL: normalize(SOUND_QUOTE)}
        result = evaluate(EQUATOR_QUESTION, calculated("40075 / 343"), pages.get)
        assert result.status == "disputed"

    def test_a_calculation_that_conflicts_with_a_quoted_answer_is_disputed(self):
        pages = {SOUND_URL: normalize(SOUND_QUOTE), URL_A: normalize("It takes 50 hours.")}
        quoted = source(URL_A, "It takes 50 hours.", 50.0, 50.0)
        result = evaluate(EQUATOR_QUESTION, calculated(extra=[quoted]), pages.get)
        assert result.status == "disputed"
        assert "estimates disagree" in result.reasons[0]

    SUN_URL = "https://en.wikipedia.org/wiki/Sun"
    SUN_QUOTE = "Volume: 1.412×10^{18} km^{3}; 1,300,000 × Earth volume;"
    EARTHS = {**QUESTION, "id": "earths", "unit": "million Earths", "answer": 1.3}

    def sun_finding(self, expression, answers=True):
        sun = self.SUN_QUOTE
        sources = [source(self.SUN_URL, sun, 1.412e18, 1.412e18).model_copy(update={"role": "input"})]
        if answers:
            sources.append(source(self.SUN_URL, sun, 1300000.0, 1.3))
        return Finding(sources=sources, ambiguous=False, changes_within_a_year=False, notes="", calculation=expression)

    @pytest.mark.parametrize("expression", ["1412000 / 1.08321", "1.412 / 1.08321"])
    @pytest.mark.parametrize("answers", [True, False])
    def test_a_calculation_left_as_a_plain_count_is_read_in_the_unit(self, expression, answers):
        # Raw Earths or millions of Earths, with or without a quoted answer beside it: the same claim.
        pages = {self.SUN_URL: normalize(self.SUN_QUOTE)}
        result = evaluate(self.EARTHS, self.sun_finding(expression, answers), pages.get)
        assert result.status == "agent_verified", result

    def test_scaling_never_rescues_a_wrong_calculation(self):
        pages = {self.SUN_URL: normalize(self.SUN_QUOTE)}
        result = evaluate(self.EARTHS, self.sun_finding("2412000 / 1.08321"), pages.get)
        assert result.status == "disputed"

    def test_an_unreadable_calculation_is_noted(self):
        pages = {SOUND_URL: normalize(SOUND_QUOTE)}
        result = evaluate(EQUATOR_QUESTION, calculated("about forty thousand"), pages.get)
        assert result.status == "needs_review"
        assert "could not evaluate" in result.notes[0]


class TestPageHandling:
    def test_page_text_survives_markup_and_footnotes(self):
        raw = "<p>Area 82,103 km<sup>2</sup><sup>[7]</sup> &amp; more</p><script>x()</script>"
        assert normalize("Area 82,103 km2 & more") in page_text(raw)

    @pytest.mark.parametrize(
        ("page", "quote"),
        [
            ("rising to **5,895 metres** at [Uhuru Peak](/wiki/Uhuru_Peak).", "rising to 5,895 metres at Uhuru Peak."),
            ("It is [Monopoly](https://x.org/wiki/Monopoly_(game)) with 40 spaces.", "It is Monopoly with 40 spaces."),
            ("Depth 1,642 m[[7]](#cite_note-7) overall.", "Depth 1,642 m overall."),
        ],
    )
    def test_markdown_in_fetched_pages_does_not_break_quotes(self, page, quote):
        assert normalize(quote) in normalize(page)

    def test_dashes_and_spacing_do_not_break_quotes(self):
        assert normalize("from 10 – 20  m") == normalize("from 10 - 20 m")

    @pytest.mark.parametrize(
        ("quote", "expected"),
        [
            ("1,280 m", [1280]),
            ("149 597 870 km", [149597870]),
            ("the (20) hits", [20]),
            ("8,848.86 m", [8848.86]),
        ],
    )
    def test_numbers_in_quotes(self, quote, expected):
        assert numbers_in(quote) == expected

    @pytest.mark.parametrize(
        ("quote", "meant"),
        [
            ("1.41 X 10^33 cm^3 (or 1.3 million times the volume of the Earth)", [1.41e33, 1.3e6]),
            ("Volume: 1.412×10^{18} km^{3}; 1,300,000 × Earth volume;", [1.412e18, 1.3e6]),
            ("Mass 1.989 × 10³⁰ kg", [1.989e30]),
            ("over 60 billion Oreo cookies", [6e10]),
            ("a charge of 1.6 × 10^-19 C", [1.6e-19]),
        ],
    )
    def test_numbers_are_also_read_as_the_quote_scales_them(self, quote, meant):
        found = numbers_in(quote)
        for value in meant:
            assert any(n == pytest.approx(value, rel=1e-9) for n in found), (value, found)

    def test_a_quote_stating_the_scaled_number_confirms_it(self):
        quote = "1.41 X 10^33 cm^3 (or 1.3 million times the volume of the Earth)"
        url = "https://sun.edu/stats"
        question = {**QUESTION, "unit": "million Earths", "answer": 1.3}
        result = evaluate(question, finding(source(url, quote, 1300000.0, 1.3)), {url: normalize(quote)}.get)
        assert result.status == "agent_verified" and result.notes == []

    @pytest.mark.parametrize(
        ("url", "domain"),
        [
            ("https://www.nasa.gov/x", "nasa.gov"),
            ("https://en.wikipedia.org/wiki/A", "wikipedia.org"),
            ("https://www.bbc.co.uk/news", "bbc.co.uk"),
        ],
    )
    def test_domains(self, url, domain):
        assert domain_of(url) == domain


def text_block():
    return SimpleNamespace(type="text", text="Searching.")


def submit_block(found):
    return SimpleNamespace(
        type="tool_use", name=SUBMIT_TOOL, input=found.model_dump(), id="toolu_1"
    )


def response(blocks, stop_reason):
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        server_tool_use=SimpleNamespace(web_search_requests=2),
    )
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage)


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def tiny_pdf(text):
    """A one-page PDF in Helvetica, built by hand so the tests need no PDF writer."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def fetched_block(url, text, source_type="text"):
    return SimpleNamespace(
        type="web_fetch_tool_result",
        content=SimpleNamespace(
            type="web_fetch_result",
            url=url,
            content=SimpleNamespace(source=SimpleNamespace(type=source_type, data=text)),
        ),
    )


class TestFetchedPages:
    def test_claudes_fetched_text_is_kept(self):
        pages = {}
        client = FakeClient(
            response(
                [fetched_block(URL_A + "/", QUOTE_A), submit_block(finding())],
                "tool_use",
            )
        )
        research(client, QUESTION, Usage(), pages)
        assert pages == {URL_A: normalize(QUOTE_A)}

    def test_failed_fetches_and_unreadable_pdfs_are_skipped(self):
        pages = {}
        failed = SimpleNamespace(
            type="web_fetch_tool_result",
            content=SimpleNamespace(type="web_fetch_tool_result_error", error_code="url_not_accessible"),
        )
        broken = fetched_block(URL_B, "JVBERi0=", "base64")  # "%PDF-" and nothing else
        garbled = fetched_block(URL_A, "not base64 at all!", "base64")
        client = FakeClient(response([failed, broken, garbled, submit_block(finding())], "tool_use"))
        research(client, QUESTION, Usage(), pages)
        assert pages == {}

    def test_a_fetched_pdf_is_read_and_its_quotes_confirm(self):
        quote = "preliminary estimate of 26.8 pounds per person in 2024"
        url = "https://ers.usda.gov/outlooks/FTS-382.pdf?v=21640"
        pdf = fetched_block(url, base64.b64encode(tiny_pdf(f"Bananas: a {quote}.")).decode(), "base64")
        pages = {}
        research(FakeClient(response([pdf, submit_block(finding())], "tool_use")), QUESTION, Usage(), pages)
        assert normalize(quote) in pages[page_key(url)]
        question = {**QUESTION, "unit": "pounds", "answer": 27}
        result = evaluate(question, finding(source(url, quote, 26.8, 26.8)), lambda u: pages.get(page_key(u)))
        assert result.status == "agent_verified"

    def test_our_own_fetch_reads_a_pdf(self, monkeypatch):
        body = tiny_pdf("Average of 13,735 miles in 2024")

        class Reply(io.BytesIO):
            headers = {"Content-Type": "application/pdf"}

        monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Reply(body))
        assert normalize("13,735 miles") in fetch_page("https://fhwa.dot.gov/report.pdf")

    def test_pdf_text_of_a_damaged_file_is_none(self):
        assert pdf_text(tiny_pdf("x")[:40]) is None

    def test_a_run_uses_claudes_copy_when_a_site_blocks_our_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("server.questions.verify.fetch_page", lambda url: None)
        path = tmp_path / "bank.json"
        questions = [dict(QUESTION)]
        client = FakeClient(
            response(
                [
                    fetched_block(URL_A, f"Intro. {QUOTE_A}"),
                    fetched_block(URL_B, f"History. {QUOTE_B}"),
                    submit_block(finding()),
                ],
                "tool_use",
            )
        )
        run(client, questions, questions, path, workers=1)
        assert questions[0]["status"] == "agent_verified"

    def test_quotes_are_still_checked_against_claudes_copy(self, tmp_path, monkeypatch):
        monkeypatch.setattr("server.questions.verify.fetch_page", lambda url: None)
        path = tmp_path / "bank.json"
        questions = [dict(QUESTION)]
        client = FakeClient(
            response(
                [
                    fetched_block(URL_A, "This page says something else entirely."),
                    fetched_block(URL_B, "So does this one."),
                    submit_block(finding()),
                ],
                "tool_use",
            )
        )
        run(client, questions, questions, path, workers=1)
        assert questions[0]["status"] == "needs_review"


class TestAgentLoop:
    def test_the_stored_answer_never_reaches_the_model(self):
        question = {**QUESTION, "answer": 987654}
        client = FakeClient(response([submit_block(finding())], "tool_use"))
        research(client, question, Usage(), {})
        assert "987654" not in json.dumps(client.calls[0]["messages"])

    def test_returns_the_submitted_finding(self):
        client = FakeClient(response([text_block(), submit_block(finding())], "tool_use"))
        assert research(client, QUESTION, Usage(), {}) == finding()

    def test_continues_after_pause_turn(self):
        client = FakeClient(
            response([text_block()], "pause_turn"),
            response([submit_block(finding())], "tool_use"),
        )
        assert research(client, QUESTION, Usage(), {}) == finding()
        assert client.calls[1]["messages"][-1]["role"] == "assistant"

    def test_gives_up_after_too_many_pauses(self):
        client = FakeClient(*[response([text_block()], "pause_turn") for _ in range(6)])
        assert research(client, QUESTION, Usage(), {}) is None
        assert client.responses == []

    @pytest.mark.parametrize("stop_reason", ["end_turn", "refusal", "max_tokens"])
    def test_no_submission_means_no_finding(self, stop_reason):
        client = FakeClient(response([text_block()], stop_reason))
        assert research(client, QUESTION, Usage(), {}) is None

    def test_uses_fallbacks_and_tracks_usage(self):
        usage = Usage()
        client = FakeClient(response([submit_block(finding())], "tool_use"))
        research(client, QUESTION, usage, {})
        assert client.calls[0]["betas"] == [FALLBACK_BETA]
        assert client.calls[0]["fallbacks"] == "default"
        assert (usage.input_tokens, usage.output_tokens, usage.searches) == (100, 50, 2)


class TestRunErrors:
    def failing_client(self, error, *responses):
        client = FakeClient(*responses)
        def create(**kwargs):
            if client.responses:
                return client.responses.pop(0)
            raise error
        client.beta.messages.create = create
        return client

    def test_one_failed_call_leaves_that_question_and_finishes_the_rest(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "server.questions.verify.evaluate",
            lambda question, found, fetch: verdict(found),
        )
        path = tmp_path / "bank.json"
        questions = [{**QUESTION, "id": "first"}, {**QUESTION, "id": "second"}]
        client = self.failing_client(
            ValueError("credit balance too low"),
            response([submit_block(finding())], "tool_use"),
        )
        run(client, questions, questions, path, workers=1)
        assert [q["status"] for q in questions] == ["agent_verified", "unverified"]
        printed = capsys.readouterr().out
        assert "credit balance too low" in printed
        assert "'skipped': 1" in printed

    def test_fatal_errors_stop_the_run(self, tmp_path):
        questions = [dict(QUESTION)]
        client = self.failing_client(PermissionError("bad key"))
        with pytest.raises(PermissionError):
            run(client, questions, questions, tmp_path / "bank.json", workers=1, fatal=(PermissionError,))

    def test_no_key_stops_before_any_question_and_logs_no_run(self, tmp_path, monkeypatch, capsys):
        import types

        import anthropic

        from server.questions import verify

        monkeypatch.setattr(anthropic, "Anthropic", lambda: types.SimpleNamespace(api_key=None, auth_token=None))
        monkeypatch.setattr(verify, "RUN_LOG", tmp_path / "runs.jsonl")
        monkeypatch.setattr("sys.argv", ["verify", "--limit", "3", "--model", "haiku"])
        assert verify.main() == 1
        printed = capsys.readouterr().out
        assert "No API key" in printed and "skipped" not in printed
        assert not (tmp_path / "runs.jsonl").exists()

    def test_a_client_with_a_key_or_token_can_run(self):
        import types

        from server.questions.verify import has_credentials

        assert has_credentials(types.SimpleNamespace(api_key="k", auth_token=None))
        assert has_credentials(types.SimpleNamespace(api_key=None, auth_token="t"))
        assert not has_credentials(types.SimpleNamespace(api_key=None, auth_token=None))
        assert not has_credentials(types.SimpleNamespace(api_key="", auth_token=None))


class TestModelChoice:
    def test_sonnet_is_the_default(self):
        client = FakeClient(response([submit_block(finding())], "tool_use"))
        research(client, QUESTION, Usage(), {})
        assert client.calls[0]["model"] == "claude-sonnet-5-5"

    def test_haiku_uses_basic_web_tools_and_no_fallback(self):
        client = FakeClient(response([submit_block(finding())], "tool_use"))
        research(client, QUESTION, Usage(), {}, MODELS["haiku"])
        call = client.calls[0]
        assert call["model"] == "claude-haiku-5-5"
        assert [tool.get("type") for tool in call["tools"][:2]] == [
            "web_search_20250305",
            "web_fetch_20250910",
        ]
        assert "fallbacks" not in call
        assert "betas" not in call

    def test_cost_uses_the_chosen_models_prices(self):
        usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000, searches=100)
        assert usage.dollars(MODELS["opus"]) == 25
        assert usage.dollars(MODELS["sonnet"]) == 13
        assert usage.dollars(MODELS["haiku"]) == pytest.approx(1.6)

    def test_the_model_used_is_recorded(self):
        question = dict(QUESTION)
        apply_verdict(question, finding(), verdict(finding()), MODELS["haiku"])
        assert question["verification"]["model"] == "claude-haiku-5-5"

    def test_each_run_s_cost_is_logged_for_the_dashboard(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        log_run(path, MODELS["sonnet"], 4, Usage(input_tokens=1_000_000, output_tokens=0, searches=0))
        log_run(path, MODELS["haiku"], 2, Usage(input_tokens=0, output_tokens=0, searches=100))
        first, second = (json.loads(line) for line in path.read_text().splitlines())
        assert (first["model"], first["questions"], first["usd"]) == ("claude-sonnet-5-5", 4, 2.0)
        assert (second["searches"], second["usd"]) == (100, 1.0)


class TestBank:
    def test_the_agent_never_changes_an_answer_or_grants_human_status(self):
        question = {**QUESTION, "answer": 250}
        found = finding()
        apply_verdict(question, found, verdict(found, question=question))
        assert question["answer"] == 250
        assert question["status"] == "disputed"

        passed = dict(QUESTION)
        apply_verdict(passed, found, verdict(found))
        assert passed["status"] == "agent_verified"
        assert passed["verification"]["sources"][0]["quote"] == QUOTE_A

    def test_agent_verified_questions_are_servable_and_review_ones_are_not(self):
        passed, review = dict(QUESTION), dict(QUESTION)
        apply_verdict(passed, finding(), verdict(finding()))
        apply_verdict(review, None, verdict(None))
        questions = [Question.model_validate(q) for q in (passed, review)]
        assert servable(questions) == [questions[0]]
        assert check_bank(questions[:1]) == []

    def test_agent_verified_without_evidence_fails_validation(self):
        question = Question.model_validate({**QUESTION, "status": "agent_verified"})
        assert check_bank([question]) == ["tower: agent_verified without evidence"]

    def test_selection_skips_finished_and_unanswered_questions(self):
        questions = [
            {"status": "unverified", "answer": 1},
            {"status": "needs_review", "answer": 1},
            {"status": "agent_verified", "answer": 1},
            {"status": "verified", "answer": 1},
            {"status": "disputed", "answer": 1},
            {"status": "unverified", "answer": None},
        ]
        assert select(questions, recheck=False) == questions[:1]
        assert select(questions, recheck=True) == questions[:2]

    def test_disputed_questions_are_never_served(self):
        question = Question.model_validate({**QUESTION, "status": "disputed"})
        assert servable([question]) == []

    def test_a_run_saves_results_to_the_bank(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "server.questions.verify.evaluate",
            lambda question, found, fetch: verdict(found),
        )
        path = tmp_path / "bank.json"
        questions = [dict(QUESTION)]
        save_bank(questions, path)
        client = FakeClient(response([submit_block(finding())], "tool_use"))
        run(client, questions, questions, path, workers=1)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved[0]["status"] == "agent_verified"
        assert saved[0]["answer"] == 330
