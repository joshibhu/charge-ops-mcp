"""Session memory and trimming. No database, no model, no network.

Trimming is the part that will break in production if it is wrong, and it
will break with a 400 from the API rather than a wrong answer — because a
`tool` message is only legal directly after an assistant message carrying
tool_calls. Slicing the last N messages can easily land on one.
"""

from chargeops.assistant.memory import Conversations


def assistant_with_tool_call(call_id: str = "c1") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id, "type": "function",
            "function": {"name": "network_summary", "arguments": "{}"},
        }],
    }


def tool_result(call_id: str = "c1") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": "some rows"}


# ── the basics ──────────────────────────────────────────────────────────────

def test_a_new_thread_starts_with_just_the_system_message():
    convos = Conversations()
    messages = convos.get("fresh")
    assert len(messages) == 1
    assert messages[0]["role"] == "system"


def test_memory_persists_between_calls():
    """The whole point. get() twice returns the SAME list, so appends stick."""
    convos = Conversations()
    convos.get("t1").append({"role": "user", "content": "hello"})
    assert len(convos.get("t1")) == 2


def test_threads_are_separate():
    """Two users must not see each other's conversation."""
    convos = Conversations()
    convos.get("alice").append({"role": "user", "content": "alice's question"})
    assert len(convos.get("bob")) == 1


def test_reset_forgets_a_thread():
    convos = Conversations()
    convos.get("t").append({"role": "user", "content": "x"})
    convos.reset("t")
    assert len(convos.get("t")) == 1


# ── trimming ────────────────────────────────────────────────────────────────

def test_nothing_is_trimmed_below_the_limit():
    convos = Conversations(max_messages=10)
    convos._threads["t"] = [{"role": "system", "content": "s"}] + [
        {"role": "user", "content": f"q{i}"} for i in range(5)
    ]
    assert convos.trim("t") == 0


def test_trimming_keeps_the_system_message():
    """Drop the system prompt and the assistant forgets its own instructions."""
    convos = Conversations(max_messages=4)
    convos._threads["t"] = [{"role": "system", "content": "SYSTEM"}] + [
        {"role": "user", "content": f"q{i}"} for i in range(20)
    ]
    convos.trim("t")
    kept = convos.get("t")
    assert kept[0]["content"] == "SYSTEM"
    assert len(kept) == 5          # system + 4


def test_trimming_never_leaves_an_orphaned_tool_message():
    """The bug this guard exists for.

    A naive last-N slice can start the window on a `tool` message, whose
    matching assistant request has been cut away. The API rejects that with
    a 400 — the whole conversation, not just that message.
    """
    convos = Conversations(max_messages=3)
    convos._threads["t"] = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q1"},
        assistant_with_tool_call("c1"),
        tool_result("c1"),
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "q2"},
        assistant_with_tool_call("c2"),
        tool_result("c2"),                 # a last-3 slice would start here
        {"role": "assistant", "content": "answer 2"},
    ]
    convos.trim("t")
    kept = convos.get("t")
    assert kept[1]["role"] != "tool", f"orphaned tool message: {kept[1]}"


def test_trimming_never_ends_on_an_unanswered_tool_call():
    """The mirror case: an assistant asking for a tool whose result was cut.

    The next request would carry a pending call with no reply.
    """
    convos = Conversations(max_messages=2)
    convos._threads["t"] = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        assistant_with_tool_call("c9"),    # a last-2 slice would end here
    ]
    convos.trim("t")
    kept = convos.get("t")
    assert not kept[-1].get("tool_calls"), f"pending tool call left at the end: {kept[-1]}"


def test_trim_reports_how_many_it_removed():
    convos = Conversations(max_messages=4)
    convos._threads["t"] = [{"role": "system", "content": "s"}] + [
        {"role": "user", "content": f"q{i}"} for i in range(10)
    ]
    before = len(convos.get("t"))
    removed = convos.trim("t")
    assert removed == before - len(convos.get("t"))
    assert removed > 0
