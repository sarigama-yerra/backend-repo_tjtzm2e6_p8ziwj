"""
Database Schemas for Classroom Platform

Each Pydantic model corresponds to one MongoDB collection (lowercased name).
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime

# Live Classroom
class Room(BaseModel):
    code: str = Field(..., description="Short code to join the room")
    title: Optional[str] = Field(None, description="Optional session title")
    teacher_name: Optional[str] = None
    require_login: bool = Field(False, description="If True, students must log in")
    created_at: Optional[datetime] = None
    # broadcast state
    broadcast_type: Optional[Literal["slides", "video", "none"]] = "none"
    slide_urls: Optional[List[str]] = None
    current_slide: Optional[int] = 0
    video_url: Optional[str] = None
    confusion_count: int = 0
    confusion_events: List[datetime] = []

class Participant(BaseModel):
    room_code: str
    role: Literal["teacher", "student"] = "student"
    nickname: Optional[str] = None
    anonymous: bool = True

class Question(BaseModel):
    room_code: str
    text: str
    author: Optional[str] = None
    anonymous: bool = True
    upvotes: int = 0
    answered: bool = False
    pinned: bool = False
    created_at: Optional[datetime] = None

class Poll(BaseModel):
    room_code: str
    question: str
    options: List[str]
    votes: List[int] = []  # same length as options
    active: bool = True
    created_at: Optional[datetime] = None

class Note(BaseModel):
    user_id: str
    room_code: Optional[str] = None
    guide_id: Optional[str] = None
    content: str
    updated_at: Optional[datetime] = None

# Study Guides
class StudyGuide(BaseModel):
    title: str
    subject: Optional[str] = None
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    exam_type: Optional[str] = None
    tags: List[str] = []
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    verified_teacher: bool = False
    description: Optional[str] = None
    # latest snapshot for quick viewing
    content_markdown: str
    parent_id: Optional[str] = None  # for forks
    votes: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class StudyGuideVersion(BaseModel):
    guide_id: str
    version: int
    content_markdown: str
    changelog: Optional[str] = None
    created_at: Optional[datetime] = None

class Collection(BaseModel):
    title: str
    description: Optional[str] = None
    owner_id: Optional[str] = None
    guide_ids: List[str] = []
    created_at: Optional[datetime] = None

# Calendar/Tasks & Time Manager
class Event(BaseModel):
    user_id: str
    title: str
    start: datetime
    end: datetime
    color: Optional[str] = None
    source: Optional[str] = None  # e.g., "teacher-deadline", "note"
    related_ids: Dict[str, str] = {}

class Task(BaseModel):
    user_id: str
    title: str
    due: Optional[datetime] = None
    priority: Optional[Literal["low", "medium", "high", "urgent"]] = "medium"
    related_ids: Dict[str, str] = {}
    completed: bool = False

class Preference(BaseModel):
    user_id: str
    focus_period_minutes: int = 50
    short_session_minutes: int = 25
    preferred_time_of_day: Optional[Literal["morning", "afternoon", "evening", "night"]] = None
    availability_weekdays: List[int] = [0,1,2,3,4]  # 0=Mon
    earliest_hour: int = 8
    latest_hour: int = 22

class SuggestionRequest(BaseModel):
    user_id: str
    horizon_days: int = 7

class Suggestion(BaseModel):
    user_id: str
    title: str
    start: datetime
    end: datetime
    reason: Optional[str] = None
    related_task_id: Optional[str] = None
