import datetime
import asyncio
import crescent
import hikari
import miru

from valerie_bot.settings import db, settings

bot = hikari.GatewayBot(
    settings.bot_token,
    intents=hikari.Intents.GUILD_MEMBERS
    | hikari.Intents.GUILDS
    | hikari.Intents.GUILD_MESSAGES,
)
commands = crescent.Client(bot)
views = miru.Client(bot)


async def create_user_thread(member: hikari.User):
    if thread := db.execute(
        "SELECT thread FROM threads WHERE user = ?", (int(member.id),)
    ).fetchone():
        try:
            await bot.rest.create_message(thread[0], f"Welcome back, <@{member.id}>!")

            return
        except hikari.NotFoundError:
            pass

    await bot.rest.add_role_to_member(
        settings.threads_guild, member, settings.threads_role
    )
    await bot.rest.add_thread_member(settings.everyone_thread, member)
    thread = await bot.rest.create_thread(
        settings.threads_channel,
        hikari.ChannelType.GUILD_PUBLIC_THREAD,
        member.global_name or member.username,
    )
    await bot.rest.create_message(
        thread,
        f"Hey, <@{member.id}>! This is your thread. You can make more threads as you please.\nCheck out <#{settings.everyone_thread}>?\nYou can rename this thread with `/rename`. And any thread, actually...\n-# ** **\n-# adding everyone to this thread, because we love you: <@&{settings.threads_role}> <3",
        role_mentions=[settings.threads_role],
        flags=hikari.MessageFlag.SUPPRESS_NOTIFICATIONS,
    )

    db.execute("INSERT INTO threads VALUES (?, ?)", (int(member.id), int(thread.id)))
    db.commit()


class ThreadCreateView(miru.View):
    should_add_users: bool = True
    thread_id: hikari.Snowflake

    def __init__(self, thread_id: hikari.Snowflake, *args, **kwargs):
        self.thread_id = thread_id
        super().__init__(*args, **kwargs)
    
    @miru.button(label="Yeah go on", style=hikari.ButtonStyle.PRIMARY)
    async def delete_message(self, ctx: miru.ViewContext, button: miru.Button):
        self.stop()

    @miru.button(label="No fuck off", style=hikari.ButtonStyle.DANGER)
    async def accept_button(self, ctx: miru.ViewContext, button: miru.Button):
        await ctx.respond("Rude.", flags=hikari.MessageFlag.EPHEMERAL)
        self.should_add_users = False
        self.stop()


@bot.listen()
async def thread(ev: hikari.GuildThreadCreateEvent):
    if ev.guild_id != settings.threads_guild:
        return

    if ev.thread.owner_id == bot.get_me().id:
        return
    
    # the bot can actually send a message before the first one
    # which is wild
    await asyncio.sleep(1)

    view = ThreadCreateView(ev.thread_id, timeout=30)
    message = await bot.rest.create_message(
        ev.thread_id,
        f"<@{ev.thread.owner_id}> Do you want to add everyone to this thread?\nIf you do not respond within 30 seconds, the default action is to add everyone.",
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
            flags=hikari.MessageFlag.SUPPRESS_NOTIFICATIONS,
        )


@bot.listen()
async def join(ev: hikari.MemberCreateEvent):
    if ev.guild_id != settings.threads_guild:
        return

    if ev.member.is_bot:
        return

    await create_user_thread(ev.member)


@commands.include
@crescent.command(
    name="manual_create_thread", description="manually create a user thread for someone"
)
class ManualCreateThread:
    user = crescent.option(hikari.User, "user")

    async def callback(self, ctx: crescent.Context) -> None:
        if ctx.guild_id != settings.threads_guild:
            return

        if ctx.user.id != settings.owner:
            await ctx.respond(
                "Well, aren't you clever?", flags=hikari.MessageFlag.EPHEMERAL
            )
            return

        await ctx.respond("Okay.", flags=hikari.MessageFlag.EPHEMERAL)
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
                "Well aren't you clever?", flags=hikari.MessageFlag.EPHEMERAL
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


@commands.include
@crescent.command(name="nickname", description="set a private nickname for someone that nobody but you will see")
class Nickname:
    who = crescent.option(hikari.User, "who")
    what = crescent.option(str, "what's your funny name, huh?")

    async def callback(self, ctx: crescent.Context) -> None:
        assert ctx.member and ctx.channel and ctx.guild
        
        interaction_start = ctx.interaction.id.created_at.astimezone(datetime.timezone.utc)
        
        if ctx.guild_id != settings.threads_guild:
            return

        if ctx.channel.parent_id != settings.threads_channel:
            await ctx.respond(
                "Well aren't you clever?", flags=hikari.MessageFlag.EPHEMERAL
            )
            return
        
        iat = db.execute(
            "SELECT iat FROM ratelimits WHERE key=?",
            (f"nickname/{ctx.member.id}",)
        ).fetchone()
        
        if iat is not None:
            last_slapped = datetime.datetime.fromisoformat(iat[0]).astimezone(datetime.timezone.utc)
            if (interaction_start - last_slapped) < datetime.timedelta(seconds=300):
                await ctx.respond("calm down there", ephemeral=True)
                return

        try:
            await bot.rest.edit_member(
                ctx.guild,
                self.who,
                nickname=self.what,
                reason=f"by request from {ctx.member.username} ({ctx.member.id})"
            )
        except hikari.RateLimitTooLongError as e:
            await ctx.respond(
                f"Go away I'll do it <t:{int(e.reset_at)}:R>",
                ephemeral=True
            )
            return
        except hikari.ForbiddenError as e:
            await ctx.respond(
                f"I couldn't do that\n-# detail: `{e}`",
                ephemeral=True
            )
            return

        await ctx.respond(
            f"<@{ctx.member.id}> set <@{self.who.id}>'s username to **{self.what.replace("*", r"\*").replace("`", r"\`")}**. Secretly.",
            user_mentions=[ctx.member.id, self.who.id]
        )
        
        db.execute(
            "INSERT INTO ratelimits VALUES (:key, :iat) ON CONFLICT(key) DO UPDATE SET iat=:iat",
            {
                "key": f"nickname/{ctx.member.id}",
                "iat": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
        )
        db.commit()


@commands.include
@crescent.command(name="hey", description="fuck off")
class Hello:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(
            "fuck off"
        )


@commands.include
@crescent.command(name="debug_ratelimits", description="debug ratelimits")
class Ratelimits:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(
            "Timeout database: "
            + "\n\n"
            + "\n".join(f"- {key}: **{iat}**" for (key, iat) in db.execute(
                "SELECT key, iat FROM ratelimits"
            ).fetchall()),
            ephemeral=True
        )


@commands.include
@crescent.command(name="ratelimit", description="set a ratelimit key")
class SetRatelimit:
    key = crescent.option(str, "ratelimit key")
    iat = crescent.option(str, "ratelimit value (iso format)")
    async def callback(self, ctx: crescent.Context) -> None:
        if ctx.user.id != settings.owner:
            await ctx.respond(
                "Well, aren't you clever?", flags=hikari.MessageFlag.EPHEMERAL
            )
            return
        
        db.execute(
            "INSERT INTO ratelimits VALUES (:key, :iat) ON CONFLICT(key) DO UPDATE SET iat=:iat",
            {
                "key": self.key,
                "iat": self.iat
            }
        )
        
        await ctx.respond(
            "Okay.",
            ephemeral=True
        )


@commands.include
@crescent.message_command(name="slap")
async def slap(ctx: crescent.Context, message: hikari.Message) -> None:
    assert ctx.member and ctx.guild
    
    if message.author.is_bot:
        await ctx.respond("you take a swing at the clanker and it breaks your hand", ephemeral=True)
        return
    
    interaction_start = ctx.interaction.id.created_at.astimezone(datetime.timezone.utc)
    
    if (interaction_start - message.created_at) > datetime.timedelta(seconds=30):
        await ctx.respond("you've got to do that within 30 seconds buddy", ephemeral=True)
        return
    
    thread = db.execute(
        "SELECT thread FROM threads WHERE user = ?", (int(ctx.member.id),)
    ).fetchone()
    
    if thread is None:
        await ctx.respond("who are you!?", ephemeral=True)
        return
    
    ratelimit_key = f"slap/{ctx.member.id}"
    ratelimit_timeout = 5
    
    if thread[0] != ctx.channel_id:
        ratelimit_key = f"slap/global/{ctx.member.id}"
        ratelimit_timeout = 86400
    
    iat = db.execute(
        "SELECT iat FROM ratelimits WHERE key=?",
        (ratelimit_key,)
    ).fetchone()
    
    if iat is not None:
        last_slapped = datetime.datetime.fromisoformat(iat[0]).astimezone(datetime.timezone.utc)
        if (interaction_start - last_slapped) < datetime.timedelta(seconds=ratelimit_timeout):
            await ctx.respond("hand hurty :(", ephemeral=True)
            return
    
    iat = db.execute(
        "SELECT iat FROM ratelimits WHERE key=?",
        (f"slap/recipient/{message.author.id}",)
    ).fetchone()
    
    if iat is not None:
        last_slapped = datetime.datetime.fromisoformat(iat[0]).astimezone(datetime.timezone.utc)
        if (interaction_start - last_slapped) < datetime.timedelta(seconds=300):
            await ctx.respond("oh my god they have suffered enough", ephemeral=True)
            return
    
    try:
        await bot.rest.edit_member(
            ctx.guild,
            message.author,
            communication_disabled_until=interaction_start + datetime.timedelta(seconds=7),
            reason=f"by request from {ctx.member.username} ({ctx.member.id})"
        )
    except hikari.RateLimitTooLongError as e:
        await ctx.respond(
            f"Go away I'll do it <t:{int(e.reset_at)}:R>",
            ephemeral=True
        )
        return
    except hikari.ForbiddenError as e:
        await ctx.respond(
            f"I couldn't do that\n-# detail: `{e}`",
            ephemeral=True
        )
        return
    
    db.execute(
        "INSERT INTO ratelimits VALUES (:key, :iat) ON CONFLICT(key) DO UPDATE SET iat=:iat",
        {
            "key": ratelimit_key,
            "iat": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
    )
    db.execute(
        "INSERT INTO ratelimits VALUES (:key, :iat) ON CONFLICT(key) DO UPDATE SET iat=:iat",
        {
            "key": f"slap/recipient/{message.author.id}",
            "iat": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
    )
    db.commit()
    
    await ctx.respond(
        f"<@{message.author.id}> got slapped for that message",
        user_mentions=[message.author.id]
    )


class GenaiConsentView(miru.View):
    did_consent: bool = False
    did_interact: bool = False
    thread_id: hikari.Snowflake

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @miru.button(label="Yeah go on", style=hikari.ButtonStyle.SUCCESS)
    async def accept_button(self, ctx: miru.ViewContext, button: miru.Button):
        self.did_consent = True
        self.did_interact: bool = True
        self.stop()

    @miru.button(label="No fuck off", style=hikari.ButtonStyle.DANGER)
    async def delete_message(self, ctx: miru.ViewContext, button: miru.Button):
        self.did_consent = False
        self.did_interact: bool = True
        self.stop()


GENAI_CONSENT_PROMPT = """
**Do you want Valerie to be able to respond to you?**

- Your content **is processed with Generative AI.**
- Your content is **not used to train Generative AI models or retained with third party inference providers.**

Your messages may be processed when:

- Valerie is current looking at the same thread as you
- You talk in Valerie's thread

-# By clicking "Yeah go on" you agree to the [Valerie Agent terms and privacy policy](https://srh.dog/legal/valerie/torment-tos).
""".strip()


GENAI_REVOKE_CONSENT_PROMPT = """
You have already consented. You may **withdraw your consent.**

In this case:
    
- Your data will be deleted as soon as possible, and within one calendar month.
"""


@commands.include
@crescent.command(name="genai", description="Enable or disable Generative AI features")
class GenaiConsent:
    async def callback(self, ctx: crescent.Context) -> None:
        if not settings.enable_genai:
            await ctx.respond("This feature isn't available right now", ephemeral=True)
            return
        
        consent_view = GenaiConsentView(timeout=120)
        consent = db.execute("SELECT consent FROM consents WHERE user=?", (ctx.user.id,)).fetchone()

        await ctx.respond(
            content=GENAI_CONSENT_PROMPT.replace(
                "{USER_CONSENT_PREFERENCE}",
                {
                    None: "not stated a preference",
                    (0,): "declined to consent",
                    (1,): "consented"
                }[consent]
            ), ephemeral=True, components=consent_view
        )

        views.start_view(consent_view)
        await consent_view.wait()
        
        if consent_view.did_interact:
            db.execute(
                "INSERT INTO consents VALUES (:user, :consent) ON CONFLICT(user) DO UPDATE SET consent=:consent",
                {"user": ctx.user.id, "consent": consent_view.did_consent},
            )
            db.commit()
            
            if consent_view.did_consent:
                await ctx.edit("Your preference has been saved", components=[])
        else:
            await ctx.edit("This interaction has timed out", components=[])
