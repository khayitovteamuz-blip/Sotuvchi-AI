"""AISalesAgent._track_off_topic: the 2nd consecutive off-topic question in a
row goes unanswered, without closing or blocking the conversation.

Detection relies on the model calling decline_off_topic (a marker tool, no
side effect) rather than matching the reply text, which is reworded by the
model every time and would make text-matching unreliable.
"""
from app.services.ai_agent import AISalesAgent


class _FakeConversation:
    def __init__(self):
        self.off_topic_streak = 0


def _trace_with(name):
    return [{"name": name, "args": {}, "result": {}}]


def test_first_off_topic_question_still_replies():
    conv = _FakeConversation()
    suppress = AISalesAgent._track_off_topic(conv, _trace_with("decline_off_topic"))
    assert suppress is False
    assert conv.off_topic_streak == 1


def test_second_consecutive_off_topic_question_is_suppressed():
    conv = _FakeConversation()
    AISalesAgent._track_off_topic(conv, _trace_with("decline_off_topic"))
    suppress = AISalesAgent._track_off_topic(conv, _trace_with("decline_off_topic"))
    assert suppress is True
    assert conv.off_topic_streak == 2


def test_further_off_topic_questions_stay_suppressed():
    conv = _FakeConversation()
    for _ in range(4):
        suppress = AISalesAgent._track_off_topic(conv, _trace_with("decline_off_topic"))
    assert suppress is True
    assert conv.off_topic_streak == 4


def test_an_on_topic_turn_resets_the_streak():
    """Not a block — the moment the customer asks a real question, replies
    resume. Compare profanity.py, which stays blocked until an operator acts."""
    conv = _FakeConversation()
    AISalesAgent._track_off_topic(conv, _trace_with("decline_off_topic"))
    AISalesAgent._track_off_topic(conv, _trace_with("decline_off_topic"))
    assert conv.off_topic_streak == 2

    suppress = AISalesAgent._track_off_topic(conv, _trace_with("search_product"))
    assert suppress is False
    assert conv.off_topic_streak == 0


def test_a_greeting_with_no_tool_calls_does_not_count_as_off_topic():
    conv = _FakeConversation()
    suppress = AISalesAgent._track_off_topic(conv, [])
    assert suppress is False
    assert conv.off_topic_streak == 0


def test_off_topic_then_on_topic_then_off_topic_does_not_suppress_immediately():
    """The streak must be consecutive — an old off-topic question a customer
    has since moved on from must not count against a fresh one."""
    conv = _FakeConversation()
    AISalesAgent._track_off_topic(conv, _trace_with("decline_off_topic"))
    AISalesAgent._track_off_topic(conv, _trace_with("check_stock"))
    suppress = AISalesAgent._track_off_topic(conv, _trace_with("decline_off_topic"))
    assert suppress is False
    assert conv.off_topic_streak == 1
