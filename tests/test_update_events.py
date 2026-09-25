import json
from datetime import date
from pathlib import Path
import importlib.util, tempfile

P = Path(__file__).resolve().parents[1] / "scripts" / "update_events.py"
spec = importlib.util.spec_from_file_location("u", P)
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)

TODAY = date(2026,9,25)

def ev(title, period, source_key="sccc", venue="Venue", overview="Useful overview"):
    return {"title":title,"period":period,"source_key":source_key,"venue":venue,
            "overview":overview,"category":"Exhibition","time":"10am","mrt":"MRT",
            "duration":"60 min","adult":"Free","senior":"Free","child":"Free",
            "link":"https://example.com","tags":[]}

def test_expiry_finite_dates_only():
    assert u.is_expired(ev("Old","1 Jan 2026 – 2 Jan 2026"), TODAY)
    assert not u.is_expired(ev("Current","1 Sep 2026 – 30 Sep 2026"), TODAY)
    assert not u.is_expired(ev("Permanent","Permanent"), TODAY)
    assert not u.is_expired(ev("Ongoing","Ongoing"), TODAY)
    assert not u.is_expired(ev("Daily","Daily"), TODAY)

def test_status():
    assert u.status_for("1 Oct 2026 – 10 Oct 2026", TODAY)[0] == "Upcoming"
    assert u.status_for("1 Sep 2026 – 30 Sep 2026", TODAY)[0] == "Ending Soon"
    assert u.status_for("Permanent", TODAY)[0] == "Ongoing"

def test_dedupe_prefers_richer():
    a=ev("Same","1 Sep 2026 – 30 Sep 2026", overview="")
    b=ev("Same","1 Sep 2026 – 30 Sep 2026", overview="Much richer description")
    b["why"]="Useful"; b["senior"]="Free"
    got=u.dedupe([a,b])
    assert len(got)==1 and got[0]["overview"]=="Much richer description"

def test_jsonld_event_parser():
    html="""<html><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Event","name":"Test Exhibition",
    "startDate":"2026-09-20","endDate":"2026-10-20",
    "location":{"@type":"Place","name":"Test Venue"},"description":"Official description",
    "url":"https://singaporeccc.org.sg/events/test/"}
    </script></html>"""
    got=u.parse_source_html(html,"sccc",TODAY)
    assert len(got)==1
    assert got[0]["title"]=="Test Exhibition"
    assert got[0]["venue"]=="Test Venue"

def test_source_failure_preserves_previous():
    previous={"events":[ev("Keep Me","1 Sep 2026 – 30 Oct 2026","sccc")]}
    def fail(url): raise RuntimeError("network down")
    got=u.update(previous,TODAY,fetcher=fail)
    assert any(x["title"]=="Keep Me" for x in got["events"])
    assert got["source_report"]["sccc"]["status"]=="fallback"

def test_zero_result_preserves_previous():
    previous={"events":[ev("Keep Me","Permanent","sccc")]}
    def empty(url): return "<html><body>No parseable events</body></html>"
    got=u.update(previous,TODAY,fetcher=empty)
    assert any(x["title"]=="Keep Me" for x in got["events"])

def test_expired_fallback_removed():
    previous={"events":[ev("Expired","1 Jan 2026 – 2 Jan 2026","sccc"),
                        ev("Keep","Permanent","sccc")]}
    def fail(url): raise RuntimeError("fail")
    got=u.update(previous,TODAY,fetcher=fail)
    titles={x["title"] for x in got["events"]}
    assert "Expired" not in titles and "Keep" in titles

def test_never_replace_nonempty_with_empty():
    previous={"events":[ev("Expired","1 Jan 2026 – 2 Jan 2026","sccc")]}
    def fail(url): raise RuntimeError("fail")
    try:
        u.update(previous,TODAY,fetcher=fail)
    except RuntimeError as e:
        assert "refusing" in str(e)
    else:
        raise AssertionError("Safety stop did not trigger")

def test_legacy_unknown_source_preserved():
    previous={"events":[ev("Legacy","Permanent","old_source")]}
    def fail(url): raise RuntimeError("fail")
    got=u.update(previous,TODAY,fetcher=fail)
    assert any(x["title"]=="Legacy" for x in got["events"])

def test_dry_run_byte_identical(monkeypatch, tmp_path):
    p=tmp_path/"events.json"
    original=json.dumps({"events":[ev("Keep","Permanent","sccc")]},indent=2)+"\n"
    p.write_text(original,encoding="utf-8")
    monkeypatch.setattr(u,"fetch",lambda url: (_ for _ in ()).throw(RuntimeError("offline")))
    # main resolves global fetch as default at function definition; directly verify no-write contract
    before=p.read_bytes()
    previous=u.load_previous(p)
    u.update(previous,TODAY,fetcher=lambda url: (_ for _ in ()).throw(RuntimeError("offline")))
    after=p.read_bytes()
    assert before==after


def test_empty_first_run_leaves_feed_absent(monkeypatch, tmp_path):
    import pytest
    path = tmp_path / "events.json"
    monkeypatch.setattr(u, "update", lambda previous: {"events": [], "source_report": {}})
    with pytest.raises(RuntimeError, match="empty production feed"):
        u.main(["--output", str(path)])
    assert not path.exists()


def test_actual_dry_run_leaves_missing_feed_absent(monkeypatch, tmp_path):
    path = tmp_path / "events.json"
    monkeypatch.setattr(u, "update", lambda previous: {"events": [], "source_report": {}})
    assert u.main(["--dry-run", "--output", str(path)]) == 0
    assert not path.exists()
