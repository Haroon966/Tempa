from __future__ import annotations

from tempa.channels.jira.intent import (
    is_ticket_cancel,
    is_ticket_confirm,
    parse_ticket_request,
    wants_jira_ticket_create,
    wants_jira_ticket_edit,
)


def test_wants_jira_ticket_create():
    assert wants_jira_ticket_create("create a jira ticket for login bug")
    assert wants_jira_ticket_create("assign me a ticket for the data fix")
    assert wants_jira_ticket_create("asign ticket to Haroon")
    assert not wants_jira_ticket_create("what is the weather")
    assert not wants_jira_ticket_create("find tickets for me")
    assert not wants_jira_ticket_create("list jira tickets for me")
    assert not wants_jira_ticket_create("show my jira issues")


def test_wants_jira_ticket_edit():
    assert wants_jira_ticket_edit("change assignee to Ali")
    assert wants_jira_ticket_edit("never mind")


def test_is_ticket_confirm():
    assert is_ticket_confirm("yes")
    assert is_ticket_confirm("go!")
    assert is_ticket_confirm("create it")
    assert not is_ticket_confirm("maybe later")


def test_is_ticket_cancel():
    assert is_ticket_cancel("never mind")
    assert is_ticket_cancel("cancel this")


def test_parse_ticket_request():
    fields = parse_ticket_request("create ticket assign to Haroon for login fix in ENG urgent")
    assert fields.assignee_hint == "Haroon"
    assert fields.project == "ENG"
    assert fields.priority == "High"
    assert "login" in fields.summary.lower() or "fix" in fields.summary.lower()
