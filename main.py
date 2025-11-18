from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from datetime import datetime

# ---------- DATABASE SETUP ----------

DATABASE_URL = "sqlite:///./pokemon_club.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Trainer(Base):
    __tablename__ = "trainers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)          # Real name
    grade = Column(Integer, nullable=True)
    nickname = Column(String, nullable=True)                   # Trainer nickname
    showdown_name = Column(String, nullable=True, index=True)  # Pokémon Showdown username
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    rank_points = Column(Integer, default=0)                   # Progression points


class Battle(Base):
    __tablename__ = "battles"
    id = Column(Integer, primary_key=True, index=True)
    trainer1_id = Column(Integer, ForeignKey("trainers.id"), nullable=False)
    trainer2_id = Column(Integer, ForeignKey("trainers.id"), nullable=False)
    winner_id = Column(Integer, ForeignKey("trainers.id"), nullable=False)
    format = Column(String, nullable=True)      # e.g. "gen9ou"
    replay_url = Column(String, nullable=True)  # Link to the Pokémon Showdown replay
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)

# ---------- SCHEMAS (Pydantic) ----------

class TrainerCreate(BaseModel):
    name: str = Field(..., example="Alex S.")
    grade: Optional[int] = Field(None, example=9)
    nickname: Optional[str] = Field(None, example="DragonMaster")
    showdown_name: Optional[str] = Field(None, example="alex_dragon")


class TrainerUpdate(BaseModel):
    name: Optional[str] = None
    grade: Optional[int] = None
    nickname: Optional[str] = None
    showdown_name: Optional[str] = None


class TrainerRead(BaseModel):
    id: int
    name: str
    grade: Optional[int]
    nickname: Optional[str]
    showdown_name: Optional[str]
    wins: int
    losses: int
    rank_points: int

    class Config:
        orm_mode = True


class BattleCreate(BaseModel):
    trainer1_id: int = Field(..., example=1)
    trainer2_id: int = Field(..., example=2)
    winner_id: int = Field(..., example=1)
    format: Optional[str] = Field(None, example="gen9ou")
    replay_url: Optional[str] = Field(
        None,
        example="https://replay.pokemonshowdown.com/gen9ou-1234567890"
    )


class BattleRead(BaseModel):
    id: int
    trainer1_id: int
    trainer2_id: int
    winner_id: int
    format: Optional[str]
    replay_url: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True


class PairingRequest(BaseModel):
    trainer_ids: List[int] = Field(
        ...,
        example=[1, 2, 3, 4],
        description="IDs of trainers who are present for this session.",
    )


class Pairing(BaseModel):
    trainer1_id: int
    trainer2_id: Optional[int]  # None means a bye


class PairingResponse(BaseModel):
    pairings: List[Pairing]


# ---------- APP SETUP ----------

app = FastAPI(
    title="Pokémon Club Battle API",
    description="Manage trainers, battles, and progression for Pokémon Club.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- HELPERS ----------

def _apply_battle_result(db: Session, battle: Battle):
    """Update wins/losses/rank_points based on a battle result."""
    t1 = db.query(Trainer).filter(Trainer.id == battle.trainer1_id).first()
    t2 = db.query(Trainer).filter(Trainer.id == battle.trainer2_id).first()
    winner = db.query(Trainer).filter(Trainer.id == battle.winner_id).first()

    if not t1 or not t2 or not winner:
        raise HTTPException(status_code=400, detail="Invalid trainer ID(s) in battle result.")

    if winner.id not in (t1.id, t2.id):
        raise HTTPException(status_code=400, detail="Winner must be one of the two trainers.")

    loser = t1 if winner.id == t2.id else t2

    # Update stats
    winner.wins += 1
    loser.losses += 1

    # Simple progression scoring:
    #   Win  = +3 points
    #   Loss = +1 point (for participation / discipline)
    winner.rank_points += 3
    loser.rank_points += 1

    db.commit()


# ---------- ROUTES ----------

@app.get("/", tags=["Meta"])
def root():
    return {
        "message": "Pokémon Club Battle API is live!",
        "docs": "/docs",
        "important_endpoints": [
            "/trainers",
            "/battles",
            "/leaderboard",
            "/pairings",
            "/board",
        ],
    }


# --- Trainers ---

@app.post("/trainers", response_model=TrainerRead, tags=["Trainers"])
def create_trainer(trainer: TrainerCreate, db: Session = Depends(get_db)):
    db_trainer = Trainer(
        name=trainer.name,
        grade=trainer.grade,
        nickname=trainer.nickname,
        showdown_name=trainer.showdown_name,
    )
    db.add(db_trainer)
    db.commit()
    db.refresh(db_trainer)
    return db_trainer


@app.get("/trainers", response_model=List[TrainerRead], tags=["Trainers"])
def list_trainers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    trainers = db.query(Trainer).offset(skip).limit(limit).all()
    return trainers


@app.get("/trainers/{trainer_id}", response_model=TrainerRead, tags=["Trainers"])
def get_trainer(trainer_id: int, db: Session = Depends(get_db)):
    trainer = db.query(Trainer).filter(Trainer.id == trainer_id).first()
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return trainer


@app.patch("/trainers/{trainer_id}", response_model=TrainerRead, tags=["Trainers"])
def update_trainer(trainer_id: int, update: TrainerUpdate, db: Session = Depends(get_db)):
    trainer = db.query(Trainer).filter(Trainer.id == trainer_id).first()
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")

    for field, value in update.dict(exclude_unset=True).items():
        setattr(trainer, field, value)

    db.commit()
    db.refresh(trainer)
    return trainer


@app.get("/leaderboard", response_model=List[TrainerRead], tags=["Scores"])
def leaderboard(limit: int = 50, db: Session = Depends(get_db)):
    """
    Trainers ordered by rank_points desc, then wins desc, then name asc.
    """
    trainers = (
        db.query(Trainer)
        .order_by(Trainer.rank_points.desc(), Trainer.wins.desc(), Trainer.name.asc())
        .limit(limit)
        .all()
    )
    return trainers


# --- Battles ---

@app.post("/battles", response_model=BattleRead, tags=["Battles"])
def create_battle(battle: BattleCreate, db: Session = Depends(get_db)):
    # Basic validation: trainers must be different
    if battle.trainer1_id == battle.trainer2_id:
        raise HTTPException(status_code=400, detail="A trainer cannot battle themselves.")

    if battle.winner_id not in (battle.trainer1_id, battle.trainer2_id):
        raise HTTPException(status_code=400, detail="Winner must be one of the two trainers.")

    db_battle = Battle(
        trainer1_id=battle.trainer1_id,
        trainer2_id=battle.trainer2_id,
        winner_id=battle.winner_id,
        format=battle.format,
        replay_url=battle.replay_url,
    )
    db.add(db_battle)
    db.commit()
    db.refresh(db_battle)

    _apply_battle_result(db, db_battle)

    return db_battle


@app.get("/battles", response_model=List[BattleRead], tags=["Battles"])
def list_battles(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    battles = (
        db.query(Battle)
        .order_by(Battle.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return battles


@app.get("/battles/recent", response_model=List[BattleRead], tags=["Battles"])
def recent_battles(limit: int = 10, db: Session = Depends(get_db)):
    battles = (
        db.query(Battle)
        .order_by(Battle.created_at.desc())
        .limit(limit)
        .all()
    )
    return battles


# --- Pairings ---

@app.post("/pairings", response_model=PairingResponse, tags=["Pairings"])
def create_pairings(request: PairingRequest, db: Session = Depends(get_db)):
    """
    Suggest fair-ish pairings for the given trainer IDs.
    - Looks up each trainer
    - Sorts by current rank_points (high to low)
    - Pairs neighbors: (1 vs 2), (3 vs 4), ...
    - If odd number, last trainer gets a bye.
    """
    if len(request.trainer_ids) == 0:
        raise HTTPException(status_code=400, detail="No trainer IDs provided.")

    trainers = (
        db.query(Trainer)
        .filter(Trainer.id.in_(request.trainer_ids))
        .all()
    )

    found_ids = {t.id for t in trainers}
    missing = [tid for tid in request.trainer_ids if tid not in found_ids]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Some trainer IDs were not found: {missing}",
        )

    trainers_sorted = sorted(
        trainers,
        key=lambda t: (-t.rank_points, -t.wins, t.name.lower()),
    )

    pairings: List[Pairing] = []
    i = 0
    n = len(trainers_sorted)
    while i < n:
        t1 = trainers_sorted[i]
        if i + 1 < n:
            t2 = trainers_sorted[i + 1]
            pairings.append(Pairing(trainer1_id=t1.id, trainer2_id=t2.id))
            i += 2
        else:
            pairings.append(Pairing(trainer1_id=t1.id, trainer2_id=None))
            i += 1

    return PairingResponse(pairings=pairings)


# --- HTML Leaderboard Board ---

@app.get("/board", response_class=HTMLResponse, tags=["Board"])
def board(db: Session = Depends(get_db)):
    trainers = (
        db.query(Trainer)
        .order_by(Trainer.rank_points.desc(), Trainer.wins.desc(), Trainer.name.asc())
        .all()
    )

    rows = ""
    for t in trainers:
        rows += f"""
        <tr>
            <td>{t.name}</td>
            <td>{t.nickname or ""}</td>
            <td>{t.showdown_name or ""}</td>
            <td>{t.wins}</td>
            <td>{t.losses}</td>
            <td>{t.rank_points}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <title>Pokémon Club Leaderboard</title>
        <!-- Auto-refresh every 10 seconds -->
        <meta http-equiv="refresh" content="10">
        <style>
            body {{
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #111827;
                color: #F9FAFB;
                padding: 20px;
            }}
            h1 {{
                text-align: center;
                margin-bottom: 10px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
                font-size: 1.1rem;
            }}
            th, td {{
                padding: 8px 12px;
                border-bottom: 1px solid #374151;
                text-align: left;
            }}
            th {{
                background: #1F2937;
            }}
            tr:nth-child(even) {{
                background: #111827;
            }}
            tr:nth-child(odd) {{
                background: #020617;
            }}
        </style>
    </head>
    <body>
        <h1>Pokémon Club Leaderboard</h1>
        <p>Auto-refreshes every 10 seconds.</p>
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Nickname</th>
                    <th>Showdown</th>
                    <th>Wins</th>
                    <th>Losses</th>
                    <th>Points</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </body>
    </html>
    """
    return html

