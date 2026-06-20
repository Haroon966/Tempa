from tempa.channels.gmail.query import extract_gmail_query
from tempa.channels.gmail.whatsapp_format import format_whatsapp_email_list


def test_gmail_query_hostinger_from():
    plan = extract_gmail_query("any mail from hostinger", "")
    assert plan.primary == "in:inbox from:hostinger"


def test_gmail_query_hostinger_related():
    plan = extract_gmail_query("any mail related to hostinger", "")
    assert plan.primary == "in:inbox hostinger"


def test_gmail_query_typo_from_has_fallback():
    plan = extract_gmail_query("any mail from hostinfer", "")
    assert plan.primary == "in:inbox from:hostinfer"
    assert any("hostinger" in fb for fb in plan.fallbacks)


def test_gmail_query_recent_inbox():
    plan = extract_gmail_query("Show my recent inbox emails", "")
    assert plan.primary == "in:inbox"


def test_gmail_query_unread():
    plan = extract_gmail_query("unread emails", "")
    assert plan.primary == "is:unread in:inbox"


def test_gmail_query_last_week():
    plan = extract_gmail_query("hostinger emails last week", "")
    assert "newer_than:7d" in plan.primary
    assert "hostinger" in plan.primary


def test_gmail_query_follow_up_context():
    plan = extract_gmail_query(
        "any more?",
        "",
        recent_context=["any mail from hostinger", "thanks"],
    )
    assert "hostinger" in plan.primary


def test_whatsapp_email_format():
    text = format_whatsapp_email_list(
        {
            "count": 1,
            "query": "in:inbox from:hostinger",
            "messages": [
                {
                    "subject": "Domain expired",
                    "from": "Hostinger <team@info.hostinger.com>",
                    "date": "Mon, 10 Jun 2025 12:00:00 +0000",
                    "snippet": "Your domain will expire soon",
                    "unread": True,
                }
            ],
        }
    )
    assert "Domain expired" in text
    assert "Hostinger" in text
    assert "unread" in text
