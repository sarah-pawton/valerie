import logging
from hikari.api import ComponentBuilder, MessageActionRowBuilder
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
logger = logging.getLogger(__name__)


async def create_user_thread(member: hikari.User):
    if thread := db.execute(
        "SELECT thread FROM threads WHERE user = ? AND is_primary = TRUE", (int(member.id),)
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

    db.execute("INSERT INTO threads VALUES (?, ?, TRUE)", (int(member.id), int(thread.id)))
    db.commit()


class ThreadCreateView(miru.View):
    is_personal: bool = False
    thread_id: hikari.Snowflake

    def __init__(self, thread_id: hikari.Snowflake, *args, **kwargs):
        self.thread_id = thread_id
        super().__init__(*args, **kwargs)
    
    @miru.button(label="No, it's not personal", style=hikari.ButtonStyle.PRIMARY)
    async def not_personal(self, ctx: miru.ViewContext, button: miru.Button):
        self.stop()
    
    @miru.button(label="Yes, it's personal", style=hikari.ButtonStyle.SECONDARY)
    async def personal(self, ctx: miru.ViewContext, button: miru.Button):
        self.is_personal = True
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
        f"<@{ev.thread.owner_id}> **Is this thread a personal thread?**\nYou should select 'Yes' if the primary topic of this thread is you.",
        components=view,
        user_mentions=[ev.thread.owner_id]
    )

    views.start_view(view)
    await view.wait()

    try:
        await message.delete()
    except hikari.NotFoundError:
        pass  # idc

    if view.is_personal:
        db.execute("INSERT INTO threads VALUES (?, ?, FALSE)", (int(ev.thread.owner_id), int(ev.thread.id),))
        db.commit()


@commands.include
@crescent.command(
    name="manual_thread_deassign", description="assign this thread to a user"
)
class ThreadAssign():
    async def callback(self, ctx: crescent.Context) -> None:
        if ctx.user.id != settings.owner:
            await ctx.respond(
                "Well, aren't you clever?", flags=hikari.MessageFlag.EPHEMERAL
            )
            return
        
        db.execute("DELETE FROM threads WHERE thread = ? AND is_primary = FALSE", (int(ctx.channel_id),))
        db.commit()


@commands.include
@crescent.command(
    name="manual_thread_assign", description="assign this thread to a user"
)
class Thread():
    user = crescent.option(hikari.User, "user")
    
    async def callback(self, ctx: crescent.Context) -> None:
        if ctx.user.id != settings.owner:
            await ctx.respond(
                "Well, aren't you clever?", flags=hikari.MessageFlag.EPHEMERAL
            )
            return
        
        db.execute("INSERT INTO threads VALUES (?, ?, FALSE)", (int(ctx.user.id), int(ctx.channel_id),))
        db.commit()


@commands.include
@crescent.command(
    name="manual_create_onboarding", description="perform the onboarding flow"
)
class ManualCreateOnboarding():
    async def callback(self, ctx: crescent.Context) -> None:
        assert ctx.channel
        
        if ctx.user.id != settings.owner:
            await ctx.respond(
                "Well, aren't you clever?", flags=hikari.MessageFlag.EPHEMERAL
            )
            return
        
        await ctx.app.rest.create_message(
            ctx.channel.id,
            "You pull up to the place Valerie told you about, and she's nowhere to be found.\n-# To access the server, **click the button.**",
            component=ctx.app.rest.build_message_action_row()
                .add_interactive_button(
                    hikari.ButtonStyle.PRIMARY,
                    "begin-onboarding",
                    label="Text her"
                )
        )


@bot.listen(hikari.InteractionCreateEvent)
async def on_component_interaction(event: hikari.InteractionCreateEvent):
    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return
    
    assert event.interaction.guild_id
    
    me = bot.get_me()
    assert me
    
    def dialogue_environment(content: str, actions: MessageActionRowBuilder | None = None):
        return hikari.impl.ContainerComponentBuilder(
            components=[
                hikari.impl.TextDisplayComponentBuilder(content=content),
                *([actions] if actions is not None else [])
            ]
        )
    
    def dialogue_bot(content: str, actions: MessageActionRowBuilder | None = None):
        return hikari.impl.ContainerComponentBuilder(
            components=[
                hikari.impl.SectionComponentBuilder(
                    accessory=hikari.impl.ThumbnailComponentBuilder(
                        media=me.make_avatar_url() or me.default_avatar_url
                    ),
                    components=[
                        hikari.impl.TextDisplayComponentBuilder(content="-# **VALERIE**"),
                        hikari.impl.TextDisplayComponentBuilder(content=content),
                    ]
                ),
                *([actions] if actions is not None else [])
            ]
        )
    
    def dialogue_user(content: str, actions: MessageActionRowBuilder | None = None):
        return hikari.impl.ContainerComponentBuilder(
            components=[
                hikari.impl.SectionComponentBuilder(
                    accessory=hikari.impl.ThumbnailComponentBuilder(
                        media=event.interaction.user.make_avatar_url() or me.default_avatar_url
                    ),
                    components=[
                        hikari.impl.TextDisplayComponentBuilder(content="-# **YOU**"),
                        hikari.impl.TextDisplayComponentBuilder(content=content),
                    ]
                ),
                *([actions] if actions is not None else [])
            ]
        )
    
    interaction_id = event.interaction.custom_id
    
    def hallway_interact(village, threads, town_hall):
        return hikari.impl.MessageActionRowBuilder(
            components=[
                hikari.impl.TextSelectMenuBuilder(
                    custom_id=f"onboarding-select-2-{''.join(['y' if x else 'n' for x in [village, threads, town_hall]])}",
                    options=[
                        *([hikari.impl.SelectOptionBuilder(
                            label="Village?",
                            value="village",
                            emoji="💬"
                        )] if village else []),
                        
                        *([hikari.impl.SelectOptionBuilder(
                            label="Threads?",
                            value="threads",
                            emoji="💬"
                        )] if threads else []),
                        
                        *([hikari.impl.SelectOptionBuilder(
                            label="Town hall?",
                            value="town_hall",
                            emoji="💬"
                        )] if town_hall else []),
                        
                        hikari.impl.SelectOptionBuilder(
                            label="Keep going",
                            value="continue",
                            description="Exit dialogue",
                            emoji="⬅️",
                        ),
                    ]
                )
            ]
        )
    
    if interaction_id == "begin-onboarding":
        await event.interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            flags=hikari.MessageFlag.EPHEMERAL,
            components=[
                dialogue_user("> hey, where are you?\n> -# **Read** · 3m"),
                dialogue_bot("> i'm coming give me a sec\n> -# Now"),
                hikari.impl.SeparatorComponentBuilder(divider=False, spacing=hikari.SpacingType.SMALL),
                dialogue_environment("Right on cue, she appears."),
                hikari.impl.SeparatorComponentBuilder(divider=False, spacing=hikari.SpacingType.SMALL),
                dialogue_bot(
                    "> let's get going, shall we?",
                    hikari.impl.MessageActionRowBuilder(
                        components=[
                            hikari.impl.TextSelectMenuBuilder(
                                custom_id="onboarding-select",
                                options=[
                                    hikari.impl.SelectOptionBuilder(
                                        label="Why should I trust you?",
                                        value="trust",
                                        emoji="💬"
                                    ),
                                    hikari.impl.SelectOptionBuilder(
                                        label="Follow her",
                                        value="continue",
                                        description="Exit dialogue",
                                        emoji="⬅️",
                                    ),
                                ]
                            )
                        ]
                    )
                )
            ]
        )
    
    elif interaction_id == "onboarding-select":
        match event.interaction.values:
            case ["trust"]:
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    flags=hikari.MessageFlag.EPHEMERAL,
                    components=[
                        dialogue_user("> why should I trust you"),
                        dialogue_bot(
                            "> bitch I don't know",
                            hikari.impl.MessageActionRowBuilder(
                                components=[
                                    hikari.impl.TextSelectMenuBuilder(
                                        custom_id="onboarding-select",
                                        options=[
                                            hikari.impl.SelectOptionBuilder(
                                                label="Follow her",
                                                value="continue",
                                                description="Exit dialogue",
                                                emoji="⬅️",
                                            ),
                                        ]
                                    )
                                ]
                            )
                        )
                    ]
                )
            case ["continue"]:
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    flags=hikari.MessageFlag.EPHEMERAL,
                    components=[
                        dialogue_environment("She hurries you along the labyrinthine mess she's brought you to. Turn, after turn, after turn, seemingly never-ending..."),
                        hikari.impl.SeparatorComponentBuilder(divider=False, spacing=hikari.SpacingType.SMALL),
                        dialogue_bot(
                            "> and so, like, the place is organised into threads, right? so everyone gets their own place to talk, and all...\n> it's kind of like a village. or a town. i mean, the communal space is called a _town_ hall but the whole thing is called a village. make it make sense?",
                            hallway_interact(True, True, True)
                        )
                    ]
                )
        
    elif interaction_id.startswith("onboarding-select-2-"):
        (
            village,
            threads,
            town_hall
        ) = (x == "y" for x in interaction_id.replace("onboarding-select-2-", ""))
        
        match event.interaction.values:
            case ["village"]:
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    flags=hikari.MessageFlag.EPHEMERAL,
                    components=[
                        dialogue_user("> village?"),
                        dialogue_bot(
                            "> yeah, i guess. everyone's together but in their own spaces. like a village?",
                            hallway_interact(False, threads, town_hall)
                        )
                    ]
                )
            case ["threads"]:
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    flags=hikari.MessageFlag.EPHEMERAL,
                    components=[
                        dialogue_user("> threads?"),
                        dialogue_bot(
                            "> it's a little channel just for you. and other people get one too. you can also make one if you've got shared interests with other people! it's like a home.\n> and you should probably avoid being too weird in someone else's home, so, you know... be nice.",
                            hallway_interact(village, False, town_hall)
                        )
                    ]
                )
            case ["town_hall"]:
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    flags=hikari.MessageFlag.EPHEMERAL,
                    components=[
                        dialogue_user("> town hall?"),
                        dialogue_bot(
                            "> it's a thread. it's for things you want to share with the class.",
                            hallway_interact(village, threads, False)
                        )
                    ]
                )
            case ["continue"]:
                await event.interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    flags=hikari.MessageFlag.EPHEMERAL,
                    components=[
                        dialogue_bot("> okay, we're here! just one last thing—i need you to sign this."),
                        hikari.impl.SeparatorComponentBuilder(divider=False, spacing=hikari.SpacingType.SMALL,),
                        dialogue_environment("She hands you this and a blood lancet."),
                        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.LARGE,),
                        hikari.impl.ContainerComponentBuilder(
                            components=[
                                hikari.impl.TextDisplayComponentBuilder(content="1. **I WILL ACT IN GOOD FAITH.**\n  I will be kind and thoughtful in how I communicate and avoid being destructive or inflammatory.\n\n2. **I WILL RESPECT THE COMMUNITY.**\n  I will not use the server's spaces for sexual activity. I will not send personal things to the town hall, or other people's threads, that are better suited to my own thread.\n\n3. **I WILL RESPECT OTHER PEOPLE'S SPACES.**\n  I will not derail other people's conversations, talk over the thread's owner or be unduly intimate, sexual or flirtatious in other people's spaces where it is not welcome, or in the town hall.\n\n4. **I WILL LEAVE A SPACE IF I DO NOT LIKE IT.**\n  I will use the \"Leave Thread\" button liberally if I do not like parts of the community.\n\n5. **I WILL CULTIVATE THE SPACE I WANT TO BE IN.**\n  I will tell people to stop talking in my thread if they're making me uncomfortable, or ask people to switch from a topic of conversation. "),
                                hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.LARGE,),
                                hikari.impl.TextDisplayComponentBuilder(content="I sign, in blood, this covenant and agree to abide by its terms."),
                                hikari.impl.MessageActionRowBuilder(
                                    components=[
                                        hikari.impl.InteractiveButtonBuilder(
                                            style=hikari.ButtonStyle.DANGER,
                                            label="Sign the contract",
                                            custom_id="onboarding-finish",
                                        ),
                                    ]
                                ),
                            ]
                        ),
                    ]
                )

    elif interaction_id == "onboarding-finish":
        await bot.rest.add_role_to_member(
            event.interaction.guild_id,
            event.interaction.user,
            settings.threads_role
        )
        await create_user_thread(event.interaction.user)
        await event.interaction.create_initial_response(
            response_type=hikari.ResponseType.MESSAGE_CREATE,
            flags=hikari.MessageFlag.EPHEMERAL,
            components=[
                dialogue_bot("> you're in!\n> oh—let me get you something for your finger...")
            ]
        )


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
        
        is_self_rename = self.who.id == ctx.member.id
        
        if not is_self_rename:
            iat = db.execute(
                "SELECT iat FROM ratelimits WHERE key=?",
                (f"nickname/{ctx.member.id}",)
            ).fetchone()
            
            if iat is not None:
                last_slapped = datetime.datetime.fromisoformat(iat[0]).astimezone(datetime.timezone.utc)
                if (interaction_start - last_slapped) < datetime.timedelta(seconds=86400):
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
        
        if is_self_rename:
            await ctx.respond(
                "Okay.",
                ephemeral=True
            )
        else:
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
        "SELECT thread FROM threads WHERE user = ? AND thread = ?", (int(ctx.member.id), int(ctx.channel_id))
    ).fetchone()
    
    ratelimit_key = f"slap/{ctx.member.id}"
    ratelimit_timeout = 5
    
    if thread is None:
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
    if not isinstance(event.interaction, hikari.ComponentInteraction):
            return
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
