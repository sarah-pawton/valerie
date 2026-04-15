import hikari
from valerie_bot.settings import settings
from valerie_bot.bot import bot
from fastapi import FastAPI
import re

app = FastAPI()

@app.get("/ping")
async def ping():
    return {
        "status": "ok"
    }

PING_REGEX = re.compile(r"(?!\\)@(?!silent)(?![a-zA-Z0-9._]+\.\.)([a-zA-Z0-9._]+)")

@app.post("/threads/{thread_id}")
async def send_message(thread_id: int, content: str):
    users = PING_REGEX.findall(content)
    members = await bot.rest.fetch_members(settings.threads_guild).collect(list)
    resolved_users = {
        member.username: member
        for member in members
        if member.username in users
    }
    flags = 0
    
    if content.startswith("@silent "):
        flags |= hikari.MessageFlag.SUPPRESS_NOTIFICATIONS
        mentions = []
        content = content[8:]
    else:
        mentions = [x.id for x in resolved_users.values()]
    
    def find_sub(match: re.Match):
        username = match.group(1)
        member = resolved_users.get(username)
        
        if member is None:
            return match.group(0)
        
        return f"<@{member.id}>"
    
    content = re.sub(
        PING_REGEX,
        find_sub,
        content
    )
    
    await bot.rest.create_message(
        channel=thread_id,
        content=f"{content}\n\n-# users: {users}, resolved users: {resolved_users}, flags: {flags}",
        user_mentions=mentions,
        flags=flags
    )

@app.get("/threads/{thread_id}")
async def get_last_messages(thread_id: int):
    pass