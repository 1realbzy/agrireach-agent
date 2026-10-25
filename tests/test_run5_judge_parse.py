"""Run 5: F5's approval got "the judge model gave no verdict (KeyError: 'n')": a verdict without "n" crashed the
parser with a bare KeyError. Any malformed reply is now a named JudgeParseError whose message quotes the raw reply
(truncated), and the check still fails closed with that clear warning."""
import pytest

from agrireach import claim_check, judge, knowledge

P = knowledge.reference("APNI-SARI-2023-MAIZE:p13-topdress-timing")
ITEMS = [("Top dress at 6 weeks after planting.", [P])]
SENT = "The Right time for application of top-dressing fertilizer is at 6 weeks after planting [%s]." % P["id"]


@pytest.mark.parametrize("raw", [
    '{"verdicts": [{"verdict": "supported", "why": "ok"}]}',            # no "n" (run 5, F5)
    '{"verdicts": [{"n": "first", "verdict": "supported"}]}',           # "n" not a number
    '{"verdicts": [{"n": null, "verdict": "supported"}]}',
    '{"verdicts": ["supported"]}',                                       # not an object
    '{"verdicts": {"n": 1, "verdict": "supported"}}',                    # not a list
    '[{"n": 1, "verdict": "supported"}]',                                # no object at the top
    '{"verdicts": [{"n": 1, "verdict": "maybe"}]}',                      # unknown verdict
    '{"verdicts": [{"n": 1, "verdict": "supported"}',                    # truncated JSON
    'I cannot judge this.',                                              # no JSON
    '',
])
def test_malformed_reply_is_a_named_parse_error_quoting_the_reply(raw):
    with pytest.raises(judge.JudgeParseError) as e:
        judge.parse(raw, ITEMS)
    assert isinstance(e.value, ValueError)  # still a ValueError for existing callers
    assert "judge reply" in str(e.value) and repr(raw[:40])[1:-1][:20] in str(e.value)


def test_raw_reply_in_the_message_is_truncated():
    raw = '{"verdicts": [{"verdict": "supported", "why": "' + "x" * 5000 + '"}]}'
    with pytest.raises(judge.JudgeParseError) as e:
        judge.parse(raw, ITEMS)
    assert len(str(e.value)) < 400


def test_check_fails_closed_with_a_clear_warning_naming_the_parse_error():
    res = claim_check.check_claims(SENT, [P], judge=True,
                                   judge_call=lambda u: '{"verdicts": [{"verdict": "supported", "why": "ok"}]}')
    assert res.judge_failed and len(res.problems) == 1
    p = res.problems[0]
    assert "couldn't run" in p and "JudgeParseError" in p and "KeyError" not in p
    assert '"verdict": "supported"' in p  # the officer/auditor can see what the judge actually said
