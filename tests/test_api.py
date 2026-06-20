from tempa.rag.ingest import ingest_text, search_memory
from tempa.rag.store import COLLECTION_NAME, get_store


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_connections(client):
    res = client.get("/api/connections")
    assert res.status_code == 200
    data = res.json()
    assert "groq" in data
    assert "rag" in data


def test_unified_rag_ingest_and_search():
    store = get_store()
    assert store.collection.name == COLLECTION_NAME
    ingest_text("WhatsApp reminder about standup", tool="whatsapp", source="test-user")
    ingest_text("Meet transcript: decided to ship MVP", tool="meet", source="meet-1", meet_link="https://meet.google.com/abc-defg-hij")
    results = search_memory("standup", top_k=3)
    assert any("standup" in r["content"].lower() for r in results)


def test_memory_search_api(client):
    ingest_text("calendar event with meet link", tool="calendar", source="evt-1", meet_link="https://meet.google.com/xyz")
    res = client.post("/api/memory/search", json={"query": "meet", "top_k": 3})
    assert res.status_code == 200
    assert "results" in res.json()
