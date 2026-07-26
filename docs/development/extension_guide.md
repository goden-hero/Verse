# Extension Guide for Developers

This guide provides step-by-step instructions for extending Verse with new features, algorithms, AI actions, API endpoints, and database models.

---

## 1. How to Add a New Recommendation Strategy

Suppose you want to implement a new **Genre & Artist Clustering Recommender** (`ClusterRecommender`).

### Step 1: Create Strategy Class
Create `app/recommendations/cluster.py`:
```python
import logging
from sqlalchemy.orm import Session
from app.recommendations.base import BaseRecommender
from app.database.models import Song

logger = logging.getLogger("music_rec.recommendations.cluster")

class ClusterRecommender(BaseRecommender):
    """Recommends songs matching genre and artist clusters."""

    def recommend(
        self, song_id: int, limit: int = 10, db_session: Session | None = None
    ) -> list[tuple[int, float]]:
        if db_session is None:
            return []
        
        target = db_session.get(Song, song_id)
        if not target:
            return []

        # Find matching genre/artist songs
        candidates = (
            db_session.query(Song)
            .filter(Song.id != song_id)
            .filter(Song.original_genre == target.original_genre)
            .limit(limit)
            .all()
        )
        
        return [(s.id, 0.85) for s in candidates]
```

### Step 2: Register Strategy in Registry
In [app/recommendations/registry.py](file:///home/hisham/projects/music-rec/app/recommendations/registry.py):
```python
from app.recommendations.cluster import ClusterRecommender

_RECOMMENDER_REGISTRY["cluster"] = ClusterRecommender()
```

### Step 3: Add Selector Mapping
In [app/recommendations/selector.py](file:///home/hisham/projects/music-rec/app/recommendations/selector.py):
```python
mapping["genre cluster"] = "cluster"
```

---

## 2. How to Add a New AI Assistant Action

Suppose you want to add a new action: `filter_by_decade` (`"action": "filter_by_decade"`).

### Step 1: Define Pydantic Action Schema
In [app/assistant/schemas.py](file:///home/hisham/projects/music-rec/app/assistant/schemas.py):
```python
class FilterByDecade(BaseModel):
    """Filters library songs by release decade (e.g. 1980s)."""
    action: Literal["filter_by_decade"] = "filter_by_decade"
    decade: int  # e.g. 1980
```

### Step 2: Update `ActionType` Union
In [app/assistant/schemas.py](file:///home/hisham/projects/music-rec/app/assistant/schemas.py#L170-L192):
```python
ActionType = Annotated[
    Union[
        SearchLibrary,
        FilterByDecade,  # Add new action schema here
        ...
    ],
    Field(discriminator="action")
]
```

### Step 3: Add Execution Logic in Executor
In [app/assistant/executor.py](file:///home/hisham/projects/music-rec/app/assistant/executor.py#L39-L188):
```python
elif action_type == "filter_by_decade":
    decade_start = action_item.decade
    decade_end = decade_start + 9
    out = SearchService.search_by_year_range(decade_start, decade_end, session)
```

### Step 4: Update System Prompt Instructions
In [app/assistant/prompts.py](file:///home/hisham/projects/music-rec/app/assistant/prompts.py):
Document the new action schema in `SYSTEM_PROMPT` so Ollama understands when to emit `"action": "filter_by_decade"`.

---

## 3. How to Add a New REST API Endpoint

Suppose you want to add `GET /api/v1/songs/stats`.

### Step 1: Add Endpoint in Router
In [app/api/routes/songs.py](file:///home/hisham/projects/music-rec/app/api/routes/songs.py):
```python
@router.get("/songs/stats", response_model=dict)
def get_library_stats(db: Session = Depends(get_db)):
    """Retrieves high-level music library statistics."""
    total_songs = db.query(Song).count()
    total_artists = db.query(Song.artist).distinct().count()
    return {"total_songs": total_songs, "total_artists": total_artists}
```

---

## 4. How to Add a New Database Table / Model

Suppose you want to add a `Lyric` entity.

### Step 1: Create SQLAlchemy Model
In [app/database/models.py](file:///home/hisham/projects/music-rec/app/database/models.py):
```python
class Lyric(Base):
    __tablename__ = "lyrics"

    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    plain_text: Mapped[str | None] = mapped_column(String, nullable=True)
    synced_lrc: Mapped[str | None] = mapped_column(String, nullable=True)

    song: Mapped["Song"] = relationship(back_populates="lyric")
```

### Step 2: Add Relationship to `Song`
```python
lyric: Mapped["Lyric"] = relationship(
    back_populates="song", cascade="all, delete-orphan", uselist=False
)
```

### Step 3: Run Alembic Migration or Re-initialize DB
```bash
alembic revision --autogenerate -m "add lyrics table"
alembic upgrade head
```
