import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import (
    Room, Participant, Question, Poll, Note,
    StudyGuide, StudyGuideVersion, Collection,
    Event, Task, Preference, SuggestionRequest, Suggestion
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Classroom Platform Backend Running"}

@app.get("/schema")
def get_schema_overview():
    return {
        "collections": [
            "room", "participant", "question", "poll", "note",
            "studyguide", "studyguideversion", "collection",
            "event", "task", "preference", "suggestion"
        ]
    }

# ---------- Live Classroom Basics ----------

class RoomCreate(BaseModel):
    code: str
    title: Optional[str] = None
    teacher_name: Optional[str] = None
    require_login: bool = False

@app.post("/rooms")
def create_room(payload: RoomCreate):
    # ensure uniqueness
    existing = list(db["room"].find({"code": payload.code})) if db else []
    if existing:
        raise HTTPException(status_code=400, detail="Room code already exists")
    room = Room(**payload.model_dump())
    room.created_at = datetime.now(timezone.utc)
    inserted_id = create_document("room", room)
    return {"id": inserted_id, "code": room.code}

@app.get("/rooms/{code}")
def get_room(code: str):
    doc = db["room"].find_one({"code": code})
    if not doc:
        raise HTTPException(status_code=404, detail="Room not found")
    doc["_id"] = str(doc["_id"])  # stringify
    return doc

class BroadcastUpdate(BaseModel):
    broadcast_type: Optional[str] = None  # slides | video | none
    slide_urls: Optional[List[str]] = None
    current_slide: Optional[int] = None
    video_url: Optional[str] = None

@app.post("/rooms/{code}/broadcast")
def update_broadcast(code: str, payload: BroadcastUpdate):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        return {"updated": False}
    res = db["room"].update_one({"code": code}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"updated": True}

@app.post("/rooms/{code}/confused")
def mark_confused(code: str):
    now = datetime.now(timezone.utc)
    db["room"].update_one({"code": code}, {"$inc": {"confusion_count": 1}, "$push": {"confusion_events": now}})
    return {"ok": True}

# ---------- Anonymous Q&A ----------
class QuestionCreate(BaseModel):
    text: str
    author: Optional[str] = None
    anonymous: bool = True

@app.post("/rooms/{code}/questions")
def post_question(code: str, payload: QuestionCreate):
    if not db["room"].find_one({"code": code}):
        raise HTTPException(status_code=404, detail="Room not found")
    q = Question(room_code=code, text=payload.text, author=payload.author, anonymous=payload.anonymous, created_at=datetime.now(timezone.utc))
    q_id = create_document("question", q)
    return {"id": q_id}

@app.get("/rooms/{code}/questions")
def list_questions(code: str):
    items = db["question"].find({"room_code": code}).sort("created_at", -1)
    out = []
    for d in items:
        d["_id"] = str(d["_id"])
        out.append(d)
    return out

class QuestionVote(BaseModel):
    up: bool = True

@app.post("/questions/{qid}/vote")
def vote_question(qid: str, payload: QuestionVote):
    from bson import ObjectId
    inc = 1 if payload.up else -1
    res = db["question"].update_one({"_id": ObjectId(qid)}, {"$inc": {"upvotes": inc}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"ok": True}

class QuestionAnswer(BaseModel):
    answered: bool = True
    pinned: Optional[bool] = None

@app.post("/questions/{qid}/answer")
def answer_question(qid: str, payload: QuestionAnswer):
    from bson import ObjectId
    updates = {"answered": payload.answered}
    if payload.pinned is not None:
        updates["pinned"] = payload.pinned
    res = db["question"].update_one({"_id": ObjectId(qid)}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"ok": True}

# ---------- Notes ----------
class NoteUpsert(BaseModel):
    user_id: str
    content: str
    room_code: Optional[str] = None
    guide_id: Optional[str] = None

@app.post("/notes")
def upsert_note(payload: NoteUpsert):
    # one note per (user_id, room_code or guide_id)
    key = {"user_id": payload.user_id}
    if payload.room_code:
        key["room_code"] = payload.room_code
    if payload.guide_id:
        key["guide_id"] = payload.guide_id
    now = datetime.now(timezone.utc)
    existing = db["note"].find_one(key)
    if existing:
        db["note"].update_one(key, {"$set": {"content": payload.content, "updated_at": now}})
        return {"updated": True}
    n = Note(**payload.model_dump(), updated_at=now)
    nid = create_document("note", n)
    return {"created": True, "id": nid}

# ---------- Study Guides Hub ----------
class GuideCreate(BaseModel):
    title: str
    subject: Optional[str] = None
    difficulty: Optional[str] = None
    exam_type: Optional[str] = None
    tags: Optional[List[str]] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    verified_teacher: bool = False
    description: Optional[str] = None
    content_markdown: str
    parent_id: Optional[str] = None

@app.post("/guides")
def create_guide(payload: GuideCreate):
    now = datetime.now(timezone.utc)
    guide = StudyGuide(**{**payload.model_dump(), "created_at": now, "updated_at": now, "votes": 0, "tags": payload.tags or []})
    gid = create_document("studyguide", guide)
    version = StudyGuideVersion(guide_id=gid, version=1, content_markdown=payload.content_markdown, created_at=now)
    create_document("studyguideversion", version)
    return {"id": gid}

@app.get("/guides")
def list_guides(q: Optional[str] = None, subject: Optional[str] = None, tag: Optional[str] = None):
    filt = {}
    if q:
        filt["title"] = {"$regex": q, "$options": "i"}
    if subject:
        filt["subject"] = subject
    if tag:
        filt["tags"] = tag
    cur = db["studyguide"].find(filt).sort("votes", -1).limit(50)
    out = []
    for d in cur:
        d["_id"] = str(d["_id"])  # stringify
        out.append(d)
    return out

class GuideVote(BaseModel):
    up: bool = True

@app.post("/guides/{gid}/vote")
def vote_guide(gid: str, payload: GuideVote):
    from bson import ObjectId
    inc = 1 if payload.up else -1
    res = db["studyguide"].update_one({"_id": ObjectId(gid)}, {"$inc": {"votes": inc}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Guide not found")
    return {"ok": True}

class GuideUpdate(BaseModel):
    content_markdown: str
    changelog: Optional[str] = None

@app.post("/guides/{gid}/update")
def update_guide(gid: str, payload: GuideUpdate):
    from bson import ObjectId
    now = datetime.now(timezone.utc)
    # bump version
    latest = db["studyguideversion"].find({"guide_id": gid}).sort("version", -1).limit(1)
    latest_version = 1
    for d in latest:
        latest_version = d.get("version", 1)
    create_document("studyguideversion", StudyGuideVersion(guide_id=gid, version=latest_version + 1, content_markdown=payload.content_markdown, changelog=payload.changelog, created_at=now))
    db["studyguide"].update_one({"_id": ObjectId(gid)}, {"$set": {"content_markdown": payload.content_markdown, "updated_at": now}})
    return {"ok": True}

@app.get("/guides/{gid}")
def get_guide(gid: str):
    from bson import ObjectId
    d = db["studyguide"].find_one({"_id": ObjectId(gid)})
    if not d:
        raise HTTPException(status_code=404, detail="Guide not found")
    d["_id"] = str(d["_id"])  # stringify
    versions = list(db["studyguideversion"].find({"guide_id": gid}).sort("version", -1))
    for v in versions:
        v["_id"] = str(v["_id"])  # stringify
    d["versions"] = versions
    return d

# ---------- Collections ----------
class CollectionCreate(BaseModel):
    title: str
    description: Optional[str] = None
    owner_id: Optional[str] = None
    guide_ids: Optional[List[str]] = None

@app.post("/collections")
def create_collection(payload: CollectionCreate):
    col = Collection(**{**payload.model_dump(), "created_at": datetime.now(timezone.utc), "guide_ids": payload.guide_ids or []})
    cid = create_document("collection", col)
    return {"id": cid}

@app.get("/collections/{cid}")
def get_collection(cid: str):
    from bson import ObjectId
    d = db["collection"].find_one({"_id": ObjectId(cid)})
    if not d:
        raise HTTPException(status_code=404, detail="Collection not found")
    d["_id"] = str(d["_id"])  # stringify
    return d

# ---------- Calendar, Tasks, Preferences ----------
class EventCreate(BaseModel):
    user_id: str
    title: str
    start: datetime
    end: datetime
    color: Optional[str] = None
    source: Optional[str] = None
    related_ids: Optional[dict] = None

@app.post("/events")
def create_event(payload: EventCreate):
    evt = Event(**{**payload.model_dump(), "related_ids": payload.related_ids or {}})
    eid = create_document("event", evt)
    return {"id": eid}

@app.get("/events")
def list_events(user_id: str, start: Optional[datetime] = None, end: Optional[datetime] = None):
    filt = {"user_id": user_id}
    if start and end:
        filt["start"] = {"$gte": start}
        filt["end"] = {"$lte": end}
    cur = db["event"].find(filt).sort("start", 1)
    out = []
    for d in cur:
        d["_id"] = str(d["_id"])  # stringify
        out.append(d)
    return out

class TaskCreate(BaseModel):
    user_id: str
    title: str
    due: Optional[datetime] = None
    priority: Optional[str] = "medium"
    related_ids: Optional[dict] = None

@app.post("/tasks")
def create_task(payload: TaskCreate):
    t = Task(**{**payload.model_dump(), "related_ids": payload.related_ids or {}})
    tid = create_document("task", t)
    return {"id": tid}

@app.get("/tasks")
def list_tasks(user_id: str):
    cur = db["task"].find({"user_id": user_id}).sort("due", 1)
    out = []
    for d in cur:
        d["_id"] = str(d["_id"])  # stringify
        out.append(d)
    return out

class PrefUpsert(BaseModel):
    user_id: str
    focus_period_minutes: Optional[int] = None
    short_session_minutes: Optional[int] = None
    preferred_time_of_day: Optional[str] = None
    availability_weekdays: Optional[List[int]] = None
    earliest_hour: Optional[int] = None
    latest_hour: Optional[int] = None

@app.post("/preferences")
def upsert_preferences(payload: PrefUpsert):
    key = {"user_id": payload.user_id}
    existing = db["preference"].find_one(key)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if existing:
        db["preference"].update_one(key, {"$set": updates})
        return {"updated": True}
    pref = Preference(**{
        "user_id": payload.user_id,
        "focus_period_minutes": payload.focus_period_minutes or 50,
        "short_session_minutes": payload.short_session_minutes or 25,
        "preferred_time_of_day": payload.preferred_time_of_day,
        "availability_weekdays": payload.availability_weekdays or [0,1,2,3,4],
        "earliest_hour": payload.earliest_hour or 8,
        "latest_hour": payload.latest_hour or 22,
    })
    pid = create_document("preference", pref)
    return {"created": True, "id": pid}

# ---------- Time Manager Suggestions ----------

def _within_prefs(dt: datetime, pref: Preference) -> bool:
    w = dt.weekday()
    if pref.availability_weekdays and w not in pref.availability_weekdays:
        return False
    if dt.hour < (pref.earliest_hour or 0) or dt.hour >= (pref.latest_hour or 24):
        return False
    if pref.preferred_time_of_day == "morning" and not (5 <= dt.hour < 12):
        return False
    if pref.preferred_time_of_day == "afternoon" and not (12 <= dt.hour < 17):
        return False
    if pref.preferred_time_of_day == "evening" and not (17 <= dt.hour < 22):
        return False
    if pref.preferred_time_of_day == "night" and not (22 <= dt.hour or dt.hour < 5):
        return False
    return True

@app.post("/suggestions")
def generate_suggestions(req: SuggestionRequest):
    # pull data
    pref_doc = db["preference"].find_one({"user_id": req.user_id})
    pref = Preference(**pref_doc) if pref_doc else Preference(user_id=req.user_id)

    tasks = list(db["task"].find({"user_id": req.user_id}))
    events = list(db["event"].find({"user_id": req.user_id}))

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=req.horizon_days)

    # build busy intervals
    busy = []
    for e in events:
        busy.append((e["start"], e["end"]))

    def is_free(start: datetime, end: datetime) -> bool:
        for bs, be in busy:
            if not (end <= bs or start >= be):
                return False
        return True

    # prioritize tasks: urgent first, then due date
    def priority_value(p: str) -> int:
        order = {"urgent": 3, "high": 2, "medium": 1, "low": 0}
        return order.get(p or "medium", 1)

    tasks.sort(key=lambda t: (
        -priority_value(t.get("priority")),
        t.get("due") or now + timedelta(days=365)
    ))

    suggestions: List[Suggestion] = []

    # loop days and hours
    cursor = now.replace(minute=0, second=0, microsecond=0)
    while cursor < horizon and len(suggestions) < 20:
        end_slot = cursor + timedelta(minutes=pref.focus_period_minutes)
        if _within_prefs(cursor, pref) and is_free(cursor, end_slot):
            # find a task that benefits from this slot
            picked = None
            for t in tasks:
                picked = t
                break
            title = f"Study Session"
            related_task_id = None
            if picked:
                related_task_id = str(picked.get("_id"))
                title = f"Work on: {picked.get('title')}"
            suggestions.append(Suggestion(user_id=req.user_id, title=title, start=cursor, end=end_slot, related_task_id=related_task_id))
            # mark this interval busy
            busy.append((cursor, end_slot))
        cursor += timedelta(minutes=30)

    # return serialized
    out = []
    for s in suggestions:
        out.append({
            "user_id": s.user_id,
            "title": s.title,
            "start": s.start,
            "end": s.end,
            "related_task_id": s.related_task_id,
            "reason": s.reason,
        })
    return out

# Keep test endpoint for infra check
@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
