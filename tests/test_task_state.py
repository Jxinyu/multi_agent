from langgraph.graph import END, START, StateGraph

from multi_domain_enterprise_project.agent import supervisor_agent as supervisor_module
from multi_domain_enterprise_project.core.task_state import TaskState, TaskStatus


def _field_reducer(field_name: str):
    metadata = TaskState.model_fields[field_name].metadata
    return next(item for item in metadata if callable(item))


def test_round_scoped_list_reducers_accept_explicit_clear():
    for field_name in (
        "requested_agents",
        "pending_sub_agents",
        "finished_sub_agents",
    ):
        reducer = _field_reducer(field_name)

        assert reducer(["finance", "tech"], []) == []


def test_sub_agent_response_reducer_accepts_explicit_clear():
    reducer = _field_reducer("sub_agent_response")

    assert reducer({"finance": {"answer": "old"}}, {}) == {}


def test_reducers_still_merge_parallel_fanout_updates():
    list_reducer = _field_reducer("finished_sub_agents")
    dict_reducer = _field_reducer("sub_agent_response")

    finished = list_reducer([], ["finance"])
    finished = list_reducer(finished, ["tech", "finance"])
    responses = dict_reducer({}, {"finance": {"answer": "finance"}})
    responses = dict_reducer(responses, {"tech": {"answer": "tech"}})

    assert finished == ["finance", "tech"]
    assert responses == {
        "finance": {"answer": "finance"},
        "tech": {"answer": "tech"},
    }


def test_terminal_state_starts_next_round_with_clean_dispatch_state():
    state = TaskState(
        task_status=TaskStatus.FAILED,
        requested_agents=["finance"],
        pending_sub_agents=["finance"],
        finished_sub_agents=["finance"],
        sub_agent_input_content={"finance": "old input"},
        sub_agent_messages={"finance": ["old message"]},
        sub_agent_response={"finance": {"answer": "old answer"}},
        audit_feedback={"correction_targets": "old feedback"},
        result={"最终回复": "old result"},
        retry_count=3,
    )

    update = supervisor_module._prepare_supervisor_state(state)

    assert update == {
        "task_status": TaskStatus.ROUTING,
        "requested_agents": [],
        "pending_sub_agents": [],
        "finished_sub_agents": [],
        "sub_agent_input_content": {},
        "sub_agent_messages": {},
        "sub_agent_response": {},
        "audit_feedback": None,
        "result": None,
        "retry_count": 0,
    }


def test_audit_retry_keeps_current_round_dispatch_state():
    state = TaskState(
        task_status=TaskStatus.AUDITING,
        requested_agents=["finance"],
        audit_feedback={"correction_targets": "补充来源"},
    )

    update = supervisor_module._prepare_supervisor_state(state)

    assert update == {"task_status": TaskStatus.RETRYING}


def test_langgraph_applies_terminal_round_clear_update():
    graph_builder = StateGraph(TaskState)
    graph_builder.add_node("prepare", supervisor_module._prepare_supervisor_state)
    graph_builder.add_edge(START, "prepare")
    graph_builder.add_edge("prepare", END)
    graph = graph_builder.compile()

    result = graph.invoke(
        {
            "task_status": TaskStatus.COMPLETED,
            "requested_agents": ["finance"],
            "pending_sub_agents": ["finance"],
            "finished_sub_agents": ["finance"],
            "sub_agent_response": {"finance": {"answer": "old answer"}},
        }
    )

    assert result["task_status"] == TaskStatus.ROUTING
    assert result["requested_agents"] == []
    assert result["pending_sub_agents"] == []
    assert result["finished_sub_agents"] == []
    assert result["sub_agent_response"] == {}


def test_langgraph_merges_parallel_fanout_updates():
    graph_builder = StateGraph(TaskState)
    graph_builder.add_node(
        "finance",
        lambda state: {
            "finished_sub_agents": ["finance"],
            "sub_agent_response": {"finance": {"answer": "finance"}},
        },
    )
    graph_builder.add_node(
        "tech",
        lambda state: {
            "finished_sub_agents": ["tech"],
            "sub_agent_response": {"tech": {"answer": "tech"}},
        },
    )
    graph_builder.add_edge(START, "finance")
    graph_builder.add_edge(START, "tech")
    graph_builder.add_edge("finance", END)
    graph_builder.add_edge("tech", END)
    graph = graph_builder.compile()

    result = graph.invoke({})

    assert result["finished_sub_agents"] == ["finance", "tech"]
    assert result["sub_agent_response"] == {
        "finance": {"answer": "finance"},
        "tech": {"answer": "tech"},
    }


def test_dispatcher_consumes_pending_queue_before_fanout():
    command = supervisor_module._dispatch_pending_agents(
        TaskState(
            task_status=TaskStatus.DISPATCHED,
            pending_sub_agents=["finance", "tech"],
        )
    )

    assert command.goto == ["finance", "tech"]
    assert command.update == {
        "task_status": TaskStatus.EXECUTING,
        "pending_sub_agents": [],
    }


def test_dispatcher_routes_empty_queue_to_aggregator():
    command = supervisor_module._dispatch_pending_agents(
        TaskState(task_status=TaskStatus.EXECUTING)
    )

    assert command.goto == "aggregator"
    assert command.update == {"task_status": TaskStatus.AGGREGATING}
