import crescent
import hikari
import miru
import sqlite3

# from valerie_bot.genai import setup_genai
from valerie_bot.settings import Settings

db = sqlite3.connect("state.db")
settings = Settings()  # type: ignore
bot = hikari.GatewayBot(settings.bot_token, intents=hikari.Intents.GUILD_MEMBERS | hikari.Intents.GUILDS | hikari.Intents.GUILD_MESSAGES)
commands = crescent.Client(bot)
views = miru.Client(bot)

db.execute("CREATE TABLE IF NOT EXISTS threads (user, thread);")

# setup_genai(settings, bot, commands, views)


async def create_user_thread(member: hikari.User):
    if thread := db.execute("SELECT thread FROM threads WHERE user = ?", (int(member.id),)).fetchone():
        try:
            await bot.rest.create_message(
                thread[0],
                f"Welcome back, <@{member.id}>!"
            )
            
            return
        except hikari.NotFoundError:
            pass
    
    await bot.rest.add_role_to_member(settings.threads_guild, member, settings.threads_role)
    await bot.rest.add_thread_member(settings.everyone_thread, member)
    thread = await bot.rest.create_thread(settings.threads_channel, hikari.ChannelType.GUILD_PUBLIC_THREAD, member.global_name or member.username)
    await bot.rest.create_message(
        thread,
        f"Hey, <@{member.id}>! This is your thread. You can make more threads as you please.\nCheck out <#{settings.everyone_thread}>?\nYou can rename this thread with `/rename`. And any thread, actually...\n-# ** **\n-# adding everyone to this thread, because we love you: <@&{settings.threads_role}> <3",
        role_mentions=[settings.threads_role],
        flags=hikari.MessageFlag.SUPPRESS_NOTIFICATIONS
    )
    
    db.execute("INSERT INTO threads VALUES (?, ?)", (int(member.id), int(thread.id)))
    db.commit()


class ThreadCreateView(miru.View):
    should_add_users: bool = True
    thread_id: hikari.Snowflake

    def __init__(self, thread_id: hikari.Snowflake, *args, **kwargs):
        self.thread_id = thread_id
        super().__init__(*args, **kwargs)

    @miru.button(label="No fuck off", style=hikari.ButtonStyle.PRIMARY)
    async def accept_button(self, ctx: miru.ViewContext, button: miru.Button):
        await ctx.respond("Rude.", flags=hikari.MessageFlag.EPHEMERAL)
        self.should_add_users = False
        self.stop()

    @miru.button(label="Yeah go on", style=hikari.ButtonStyle.SECONDARY)
    async def delete_message(self, ctx: miru.ViewContext, button: miru.Button):
        self.stop()


@bot.listen()
async def thread(ev: hikari.GuildThreadCreateEvent):
    if ev.guild_id != settings.threads_guild:
        return
    
    if ev.thread.owner_id == bot.get_me().id:
        return

    view = ThreadCreateView(ev.thread_id, timeout=10)
    message = await bot.rest.create_message(
        ev.thread_id,
        f"<@{ev.thread.owner_id}> Don't add everyone to this thread?",
        components=view,
    )

    views.start_view(view)
    await view.wait()

    try:
        await message.delete()
    except hikari.NotFoundError:
        pass  # idc
    
    if view.should_add_users:
        await bot.rest.create_message(
            ev.thread_id,
            f"-# hey <@&{settings.threads_role}> <3",
            role_mentions=[settings.threads_role],
            flags=hikari.MessageFlag.SUPPRESS_NOTIFICATIONS
        )


@bot.listen()
async def join(ev: hikari.MemberCreateEvent):
    if ev.guild_id != settings.threads_guild:
        return
    
    if ev.member.is_bot:
        return
    
    await create_user_thread(ev.member)


@commands.include
@crescent.command(name="manual_create_thread", description="manually create a user thread for someone")
class ManualCreateThread:
    user = crescent.option(hikari.User, "user")
    
    async def callback(self, ctx: crescent.Context) -> None:
        if ctx.guild_id != settings.threads_guild:
            return
        
        if ctx.user.id != settings.owner:
            await ctx.respond(
                "Well, aren't you clever?",
                flags=hikari.MessageFlag.EPHEMERAL
            )
            return
            
        await ctx.respond(
            "Okay.",
            flags=hikari.MessageFlag.EPHEMERAL
        )
        await create_user_thread(self.user)


@commands.include
@crescent.command(name="rename", description="rename a thread")
class Rename:
    what = crescent.option(str, "what's your funny name, huh?")
    
    async def callback(self, ctx: crescent.Context) -> None:
        if ctx.guild_id != settings.threads_guild:
            return
        
        if ctx.channel.parent_id != settings.threads_channel:
            await ctx.respond(
                "Well aren't you clever?",
                flags=hikari.MessageFlag.EPHEMERAL
            )
            return
        
        try:
            await bot.rest.edit_channel(ctx.channel.id, name=self.what)
        except hikari.RateLimitTooLongError as e:
            await ctx.respond(
                f"Go away I'll do it <t:{int(e.reset_at)}:R>",
            )
            return
            
        await ctx.respond(
            "If you say so.",
        )


def main():
    bot.run(
        status=hikari.Status.IDLE,
        activity=hikari.Activity(
            name="probably taking a nap", type=hikari.ActivityType.CUSTOM
        ),
    )
