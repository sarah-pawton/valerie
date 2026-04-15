import uvicorn
import hikari
import asyncio

from valerie_bot.settings import db, settings
from valerie_bot.bot import bot
from valerie_bot.api import app

async def amain():
    config = uvicorn.Config(app)
    server = uvicorn.Server(config)
    
    await bot.start(
        status=hikari.Status.IDLE,
        activity=hikari.Activity(
            name="probably taking a nap", type=hikari.ActivityType.CUSTOM
        ),
    )
    
    async with asyncio.TaskGroup() as tg:
        tg.create_task(bot.join())
        
        if settings.enable_api:
            tg.create_task(server.serve())
        

def main():
    db.execute("CREATE TABLE IF NOT EXISTS threads (user, thread);")
    db.execute("CREATE TABLE IF NOT EXISTS consents (user PRIMARY KEY, consent);")
    db.execute("CREATE TABLE IF NOT EXISTS ratelimits (key PRIMARY KEY, iat);")
    
    try:
        import uvloop
        uvloop.run(amain())
    except ImportError:
        asyncio.run(amain())