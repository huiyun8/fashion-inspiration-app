"""End-to-end: upload → classify (mock) → filter → feedback."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient


def _tiny_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_upload_classify_filter_and_feedback(client: TestClient) -> None:
    files = {"file": ("test.png", io.BytesIO(_tiny_png()), "image/png")}
    data = {
        "designer": "E2E Designer",
        "captured_year": "2025",
        "captured_month": "4",
        "captured_season": "SS25",
    }
    r = client.post("/api/images", files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] >= 1
    assert body["designer"] == "E2E Designer"
    assert body["captured_year"] == 2025
    assert body["ai_attributes"] is not None
    gt = body["ai_attributes"].get("garment_type")

    r2 = client.get("/api/images", params={"garment_type": gt, "designer": "E2E Designer"})
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]

    r3 = client.get("/api/filters")
    assert r3.status_code == 200
    filters = r3.json()
    assert "E2E Designer" in filters["designer"]
    assert 2025 in filters["captured_year"]

    ann = {"tags": ["artisan", "market-trip"], "notes": "embroidered neckline reference"}
    r4 = client.post(f"/api/images/{body['id']}/annotations", json=ann)
    assert r4.status_code == 200, r4.text
    r5 = client.get("/api/images", params={"q": "embroidered"})
    assert r5.status_code == 200
    assert any(row["id"] == body["id"] for row in r5.json())

    r_bad_fb = client.post(f"/api/images/{body['id']}/feedback", json={})
    assert r_bad_fb.status_code == 422

    r7 = client.post(
        f"/api/images/{body['id']}/feedback",
        json={"rating": 4, "comment": "Good but sleeve detail off"},
    )
    assert r7.status_code == 200, r7.text
    fb = r7.json()
    assert fb["rating"] == 4
    assert "sleeve" in (fb["comment"] or "")

    r8 = client.get(f"/api/images/{body['id']}")
    assert r8.status_code == 200
    summary = r8.json().get("feedback_summary")
    assert summary is not None
    assert summary["count"] == 1
    assert summary["avg_rating"] == 4.0

    r9 = client.get(f"/api/images/{body['id']}/feedback", params={"include_ai_snapshot": True})
    assert r9.status_code == 200
    snap_rows = r9.json()
    assert len(snap_rows) == 1
    assert snap_rows[0].get("ai_snapshot") is not None
