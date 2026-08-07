# Knowledge directory

Living address book for Tempa: Slack channels, people (email / Slack / WhatsApp), and routing aliases.

Refresh with:

```bash
.venv/bin/python -c "from tempa.knowledge.directory import refresh_knowledge_directory; print(refresh_knowledge_directory())"
```

Or it refreshes on daemon startup with vault sync.
