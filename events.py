from sanic import Blueprint, response
import aiohttp
import logging
import aiosqlite
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

events_bp = Blueprint('events', url_prefix='/events')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SPORTSDB_API_URL = "https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t="

DATABASE_NAME = "events.db"

class Event(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    event_type: str
    category: str
    start_date: datetime
    end_date: datetime
    user_id: int
    logos: Optional[str] = None

async def get_db():
    db = await aiosqlite.connect(DATABASE_NAME)
    await db.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            event_type TEXT NOT NULL,
            category TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            logos TEXT
        )
    ''')
    await db.commit()
    return db

async def get_team_logo(session, team_name):
    try:
        async with session.get(f"{SPORTSDB_API_URL}{team_name}") as resp:
            if resp.status == 200:
                data = await resp.json()
                if data['teams'] and len(data['teams']) > 0:
                    return data['teams'][0]['strLogo']
    except Exception as e:
        logger.error(f"Failed to fetch logo for team {team_name}: {str(e)}")
    return ""

async def get_logos_for_event(session, event_name):
    teams = event_name.split(' v ')
    if len(teams) != 2:
        return None
    
    logo1 = await get_team_logo(session, teams[0])
    logo2 = await get_team_logo(session, teams[1])
    
    if not logo1 and not logo2:
        return None
    return f"{logo1}|{logo2}"

@events_bp.route('/', methods=['GET'])
async def get_all_events(request):
    async with await get_db() as db:
        async with db.execute('SELECT * FROM events') as cursor:
            events = await cursor.fetchall()
    
    event_list = [Event(id=e[0], name=e[1], description=e[2], event_type=e[3], category=e[4],
                        start_date=datetime.fromisoformat(e[5]), end_date=datetime.fromisoformat(e[6]),
                        user_id=e[7], logos=e[8]).dict() for e in events]
    return response.json(event_list)

@events_bp.route('/<event_id:int>', methods=['GET'])
async def get_event_by_id(request, event_id):
    async with await get_db() as db:
        async with db.execute('SELECT * FROM events WHERE id = ?', (event_id,)) as cursor:
            event = await cursor.fetchone()
    
    if event:
        event_data = Event(id=event[0], name=event[1], description=event[2], event_type=event[3], category=event[4],
                           start_date=datetime.fromisoformat(event[5]), end_date=datetime.fromisoformat(event[6]),
                           user_id=event[7], logos=event[8]).dict()
        return response.json(event_data)
    else:
        return response.json({'error': 'Event not found'}, status=404)

@events_bp.route('/', methods=['POST'])
async def create_event(request):
    try:
        event_data = Event(**request.json)
        
        async with aiohttp.ClientSession() as session:
            logos = await get_logos_for_event(session, event_data.name)
            event_data.logos = logos

        async with await get_db() as db:
            cursor = await db.execute('''
                INSERT INTO events (name, description, event_type, category, start_date, end_date, user_id, logos)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (event_data.name, event_data.description, event_data.event_type, event_data.category,
                  event_data.start_date.isoformat(), event_data.end_date.isoformat(), event_data.user_id, event_data.logos))
            event_data.id = cursor.lastrowid
            await db.commit()

        return response.json(event_data.dict(), status=201)
    except Exception as e:
        logger.error(f"Error creating event: {str(e)}")
        return response.json({'error': 'Internal server error'}, status=500)

@events_bp.route('/<event_id:int>', methods=['PUT'])
async def update_event(request, event_id):
    try:
        event_data = Event(**request.json, id=event_id)
        
        async with await get_db() as db:
            async with db.execute('SELECT name FROM events WHERE id = ?', (event_id,)) as cursor:
                old_event = await cursor.fetchone()
            
            if not old_event:
                return response.json({'error': 'Event not found'}, status=404)

            if event_data.name != old_event[0]:
                async with aiohttp.ClientSession() as session:
                    logos = await get_logos_for_event(session, event_data.name)
                    event_data.logos = logos

            await db.execute('''
                UPDATE events SET name=?, description=?, event_type=?, category=?, start_date=?, end_date=?, user_id=?, logos=?
                WHERE id=?
            ''', (event_data.name, event_data.description, event_data.event_type, event_data.category,
                  event_data.start_date.isoformat(), event_data.end_date.isoformat(), event_data.user_id, event_data.logos, event_id))
            await db.commit()

        return response.json(event_data.dict())
    except Exception as e:
        logger.error(f"Error updating event: {str(e)}")
        return response.json({'error': 'Internal server error'}, status=500)

@events_bp.route('/<event_id:int>', methods=['DELETE'])
async def delete_event(request, event_id):
    try:
        async with await get_db() as db:
            await db.execute('DELETE FROM events WHERE id = ?', (event_id,))
            await db.commit()
        return response.empty(status=204)
    except Exception as e:
        logger.error(f"Error deleting event: {str(e)}")
        return response.json({'error': 'Internal server error'}, status=500)