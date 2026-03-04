from dotenv import load_dotenv
load_dotenv()

from app.db import SessionLocal
from app.models import Event

EVENTS = [
    # Reemplazá por tu lista real
    {"code": "MIA-R16-03JUL", "name": "16vos - Miami - Hard Rock Stadium", "city": "Miami", "venue": "Hard Rock Stadium"},
    {"code": "ATL-R16-07JUL", "name": "8vos - Atlanta - Mercedes-Benz Stadium", "city": "Atlanta", "venue": "Mercedes-Benz Stadium"},
    {"code": "MCI-QF-11JUL", "name": "4tos - Kansas City - Arrowhead Stadium", "city": "Kansas City", "venue": "Arrowhead Stadium"},
]

def run():
    db = SessionLocal()
    try:
        for e in EVENTS:
            exists = db.query(Event).filter(Event.code == e["code"]).first()
            if not exists:
                db.add(Event(**e))
        db.commit()
        print("OK: events seeded")
    finally:
        db.close()

if __name__ == "__main__":
    run()