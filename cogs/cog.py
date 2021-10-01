from discord import Embed, TextChannel, NotFound
from discord.ext import commands
from discord.utils import utcnow
from dislash import slash_command, Option, OptionType, is_owner, SlashInteraction, BadArgument, BotMissingPermissions, ApplicationCommandError, has_guild_permissions
import discord
import json
import asyncio
from datetime import datetime
from time import strftime, localtime, time
from types import BuiltinFunctionType, FunctionType, MethodType
from json.decoder import JSONDecodeError
from random import choice
from string import ascii_letters
import aiofiles
from os import getpid
import sys
import psutil
from enum import Enum


class SubscriptionError(ApplicationCommandError):
    def __init__(self, message = None):
        super().__init__(message or "There was an error handling the eventsub subscription")

class TimezoneOptions(Enum):
    short_date = "d" #07/10/2021
    month_day_year_time = "f" #July 10, 2021 1:21 PM
    time = "t" #1:21 PM
    short_date2 = "D" #July 10, 2021
    full_date_time = "F" #Saturday, July 10, 2021 1:21 PM
    long_ago = "R" #6 minutes ago
    long_time = "T" #1:21:08 PM

def DiscordTimezone(utc, format: TimezoneOptions):
    return f"<t:{int(utc)}:{format.value}>"

class pretty_time:
    def __init__(self, unix, duration=False):
        unix = float(unix)
        if not duration:
            self.unix_diff = time() - unix
        else:
            self.unix_diff = unix
        self.unix = unix
        self.years = int(str(self.unix_diff // 31536000).split('.')[0])
        self.days = int(str(self.unix_diff // 86400 % 365).split('.')[0])
        self.hours = int(str(self.unix_diff // 3600 % 24).split('.')[0])
        self.minutes = int(str(self.unix_diff // 60 % 60).split('.')[0])
        self.seconds = int(str(self.unix_diff % 60).split('.')[0])
        timezone_datetime = datetime.fromtimestamp(unix)
        self.datetime = timezone_datetime.strftime('%I:%M:%S %p %Y-%m-%d %Z')

        self.dict = {"days": self.days, "hours": self.hours, "minutes": self.minutes, "seconds": self.seconds, "datetime": self.datetime}

        full = []
        if self.years != 0:
            full.append(f"{self.years} {'year' if self.years == 1 else 'years'}")
        if self.days != 0:
            full.append(f"{self.days} {'day' if self.days == 1 else 'days'}")
        if self.hours != 0:
            full.append(f"{self.hours} {'hour' if self.hours == 1 else 'hours'}")
        if self.minutes != 0:
            full.append(f"{self.minutes} {'minute' if self.minutes == 1 else 'minutes'}")
        if self.seconds != 0:
            full.append(f"{self.seconds} {'second' if self.seconds == 1 else 'seconds'}")
        full = (', '.join(full[0:-1]) + " and " + ' '.join(full[-1:])) if len(full) > 1 else ', '.join(full)
        self.prettify = full

class RecieverCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()
        self.bot.help_command = None

    @commands.Cog.listener()
    async def on_slash_command(self, ctx):
        self.bot.log.info(f"Handling slash command {ctx.slash_command.name} for {ctx.author} in {ctx.guild.name}")

    @commands.Cog.listener()
    async def on_button_click(self, ctx):
        if not await self.bot.is_owner(ctx.author):
            return await ctx.send("You do not have permission to use this button!", ephemeral=True)
        self.bot.test = ctx
        #Extract info
        custom_id = ctx.component.custom_id.split("/")
        user_id = custom_id[1]
        broadcaster_id = custom_id[0]
        self.bot.log.info(f"Button clicked for broadcaster {broadcaster_id} with user id {user_id}")

        try:
            async with aiofiles.open("config/user_authorization.json") as f:
                user_auth = json.loads(await f.read())
        except FileNotFoundError:
            user_auth = {}
        except JSONDecodeError:
            user_auth = {}

        if user_auth.get(broadcaster_id, None) is None:
            return await ctx.send(f"<:red_tick:809191812337369118> No authorization token! You must authorize the broadcasters account with: <{self.bot.auth_url}>", ephemeral=True)

        response = await self.bot.user_api_request(method="put", url=f"https://api.twitch.tv/helix/users/blocks?target_user_id={user_id}&reason=spam&source_context=chat", user_id=broadcaster_id)
        if response.status in [400, 401]:
            return await ctx.send(f"<:red_tick:809191812337369118> Failed to block user! Status Code {response.status}", ephemeral=True)

        #Send response if no issues above
        await ctx.send("<:green_tick:809191812434231316> Blocked user!", ephemeral=True)

        #If successful, disable button
        ctx.component.disabled = True
        embed = ctx.message.embeds[0]
        embed.colour = 16711680
        await ctx.message.edit(embed=embed, components=ctx.components)

    @slash_command(description="Responds with the bots latency to discords servers")
    async def ping(self, ctx):
        gateway = int(self.bot.latency*1000)
        await ctx.send(f"Pong! `{gateway}ms` Gateway") #Message cannot be ephemeral for ping updates to show

    @slash_command(description="Owner Only: Reload the bot cogs and listeners")
    @is_owner()
    async def reload(self, ctx):
        cog_count = 0
        for ext_name in dict(self.bot.extensions).keys():
            cog_count += 1
            self.bot.reload_extension(ext_name)
        await ctx.send(f"<:green_tick:809191812434231316> Succesfully reloaded! Reloaded {cog_count} cogs!", ephemeral=True)
    
    @slash_command(description="Owner Only: Run streamer catchup manually")
    @is_owner()
    async def catchup(self, ctx):
        self.bot.log.info("Manually Running streamer catchup...")
        await self.bot.catchup_streamers()
        self.bot.log.info("Finished streamer catchup")
        await ctx.send("Finished catchup!", ephemeral=True)

    @slash_command(description="Get various bot information such as memory usage and version")
    async def botstatus(self, ctx):
        p = pretty_time(self.bot._uptime)
        embed = Embed(title=f"{self.bot.user.name} Status", colour=self.bot.colour, timestamp=utcnow())
        if self.bot.owner_id is None:
            owner_objs = [str(self.bot.get_user(user)) for user in self.bot.owner_ids]
            owners = ', '.join(owner_objs).rstrip(", ")
            is_plural = False
            if len(owner_objs) > 1:
                is_plural = True
        else:
            owners = await self.bot.fetch_user(self.bot.owner_id)
            is_plural = False
        async with aiofiles.open("config/follows.json") as f:
            callbacks = json.loads(await f.read())
        alert_count = 0
        for data in callbacks.values():
            alert_count += len(data["channels"].values())
        botinfo = f"**🏠 Servers:** {len(self.bot.guilds)}\n**🤖 Bot Creation Date:** {DiscordTimezone(int(self.bot.user.created_at.timestamp()), TimezoneOptions.month_day_year_time)}\n**🕑 Uptime:** {p.prettify}\n**⚙️ Cogs:** {len(self.bot.cogs)}\n**📈 Commands:** {len([c for c in self.bot.walk_commands()])}\n**🏓 Latency:**  {int(self.bot.latency*1000)}ms\n**🕵️‍♀️ Owner{'s' if is_plural else ''}:** {owners}\n**<:Twitch:891703045908467763> Subscribed Streamers:** {len(callbacks.keys())}\n**<:notaggy:891702828756766730> Notification Count:** {alert_count}"
        embed.add_field(name="__Bot__", value=botinfo, inline=False)
        memory = psutil.virtual_memory()
        cpu_freq = psutil.cpu_freq()
        systeminfo = f"**<:python:879586023116529715> Python Version:** {sys.version.split()[0]}\n**<:discordpy:879586265014607893> Discord.py Version:** {discord.__version__}\n**🖥️ CPU:** {psutil.cpu_count()}x @{round((cpu_freq.max if cpu_freq.max != 0 else cpu_freq.current)/1000, 2)}GHz\n**<:microprocessor:879591544070488074> Process Memory Usage:** {psutil.Process(getpid()).memory_info().rss/1048576:.2f}MB\n**<:microprocessor:879591544070488074> System Memory Usage:** {memory.used/1048576:.2f}MB ({memory.percent}%) of {memory.total/1048576:.2f}MB"
        embed.add_field(name="__System__", value=systeminfo, inline=False)
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.with_size(128))
        embed.set_footer(text=f"Client ID: {self.bot.user.id}")
        await ctx.send(embed=embed)

    @slash_command(description="Get how long the bot has been running")
    async def uptime(self, ctx):
        epoch = time() - self.bot._uptime
        conv = {
            "days": str(epoch // 86400).split('.')[0],
            "hours": str(epoch // 3600 % 24).split('.')[0],
            "minutes": str(epoch // 60 % 60).split('.')[0],
            "seconds": str(epoch % 60).split('.')[0],
            "full": strftime('%Y-%m-%d %I:%M:%S %p %Z', localtime(self.bot._uptime))
        }
        description = f"{conv['days']} {'day' if conv['days'] == '1' else 'days'}, {conv['hours']} {'hour' if conv['hours'] == '1' else 'hours'}, {conv['minutes']} {'minute' if conv['minutes'] == '1' else 'minutes'} and {conv['seconds']} {'second' if conv['seconds'] == '1' else 'seconds'}"
        embed = Embed(title="Uptime", description=description,
                            color=self.bot.colour, timestamp=datetime.utcnow())
        embed.set_footer(
            text=f"ID: {ctx.guild.id} | Bot started at {conv['full']}")
        await ctx.send(embed=embed)

    async def aeval(self, ctx, code):
        code_split = ""
        code_length = len(code.split("\\n"))
        for count, line in enumerate(code.split("\\n"), 1):
            if count == code_length:
                code_split += f"    return {line}"
            else:
                code_split += f"    {line}\n"
        combined = f"async def __ex(self, ctx):\n{code_split}"
        exec(combined)
        return await locals()['__ex'](self, ctx)

    # @slash_command(description="Evalute a string as a command")
    # async def eval(self, ctx: SlashInteraction,
    #     command: str = OptionParam(description="The string to be evaluated"),
    #     respond: bool = OptionParam(True, description="Respond with attributes and functions?"),
    # ):
    @slash_command(description="Evalute a string as a command", options=[Option("command", "The string to be evaled", type=OptionType.STRING, required=True), Option("respond", "Should the bot respond with the return values attributes and functions", type=OptionType.BOOLEAN, required=False)])
    @is_owner()
    async def eval(self, ctx: SlashInteraction, command, respond=True):
        code_string = "```nim\n{}```"
        if command.startswith("`") and command.endswith("`"):
            command = command[1:][:-1]
        try:
            resp = await self.aeval(ctx, command)
        except Exception as ex:
            await ctx.send(content=f"Exception Occurred: `{ex}`")
        else:
            if not ctx.invoked_with == "evalr" and respond:
                if type(resp) == str:
                    return await ctx.send(code_string.format(resp))

                attributes = {} #Dict of all attributes
                methods = [] #Sync methods
                amethods = [] #Async methods
                #get a list of all attributes and their values, along with all the functions in seperate lists
                for attr_name in dir(resp):
                    try:
                        attr = getattr(resp, attr_name)
                    except AttributeError:
                        pass
                    if attr_name.startswith("_"):
                        continue #Most methods/attributes starting with __ or _ are generally unwanted, skip them
                    if type(attr) not in [MethodType, BuiltinFunctionType, FunctionType]:
                        attributes[str(attr_name)] = f"{attr} [{type(attr).__name__}]"
                    else:
                        if asyncio.iscoroutinefunction(attr):
                            amethods.append(attr_name)
                        else:
                            methods.append(attr_name)
                if attributes == {}:
                    attributes["str"] = str(resp)

                #Form the long ass string of everything
                return_string = []
                if type(resp) != list:
                    stred = str(resp)
                else:
                    stred = '\n'.join([str(r) for r in resp])
                return_string += [f"Type: {type(resp).__name__}", f"Str: {stred}", '', "Attributes:"] #List return type, it's str value
                return_string += [f"{x}:    {y}" for x, y in attributes.items()]

                if methods != []:
                    return_string.append("\nMethods:")
                    return_string.append(', '.join([method for method in methods]).rstrip(", "))

                if amethods != []:
                    return_string.append("\n\nAsync/Awaitable Methods:")
                    return_string.append(', '.join([method for method in amethods]).rstrip(", "))

                d_str = ""
                for x in return_string:
                    if len(d_str + f"{x.rstrip(', ')}\n") < 1990:
                        d_str += f"{x.rstrip(', ')}\n"
                    else:
                        if len(code_string.format(d_str)) > 2000:
                            while d_str != "":
                                await ctx.send(code_string.format(d_str[:1990]))
                                d_str = d_str[1990:]
                        else:
                            await ctx.send(code_string.format(d_str))
                        d_str = f"{x.rstrip(', ')}\n"
                if d_str != "":
                    try:
                        await ctx.send(code_string.format(d_str))
                    except NotFound:
                        pass

    async def check_streamer(self, username):
        response = await self.bot.api_request(f"https://api.twitch.tv/helix/users?login={username}")
        r_json = await response.json()
        if r_json["data"] != []:
            return r_json["data"][0]
        else:
            return False

    async def check_channel_permissions(self, ctx, channel):
        if isinstance(channel, int): channel = self.bot.get_channel(channel)
        else: channel = self.bot.get_channel(channel.id)
        if not isinstance(channel, TextChannel):
            raise BadArgument(f"Channel {channel.mention} is not a text channel!")

        perms = {"view_channel": True, "read_message_history": True, "send_messages": True}
        permissions = channel.permissions_for(ctx.guild.me)

        missing = [perm for perm, value in perms.items() if getattr(permissions, perm) != value]
        if not missing:
            return True

        raise BotMissingPermissions(missing)

    @slash_command(description="List all the active follow alerts setup in this server")
    @has_guild_permissions(administrator=True)
    async def listfollowalerts(self, ctx):
        async with aiofiles.open("config/follows.json") as f:
            callback_info = json.loads(await f.read())
        uwu = f"```nim\n{'Channel':15s} {'Alert Channel':22s}\n"
        for x, y in callback_info.items():
            if str(ctx.guild.id) in y["channels"].keys():
                info = y["channels"][str(ctx.guild.id)]

                alert_channel = info.get("notif_channel_id", None)
                alert_channel = ctx.guild.get_channel(alert_channel)
                if alert_channel is not None:
                    alert_channel = "#" + alert_channel.name
                else:
                    alert_channel = ""

                if len(uwu + f"{x:15s} {alert_channel:22s}\n") > 1800:
                    uwu += "```"
                    await ctx.send(uwu)
                    uwu = "```nim\n"
                uwu += f"{x:15s} {alert_channel:22s}\n"
        uwu += "```"
        await ctx.send(uwu)

    @slash_command(description="Add alerts for the specific streamer", options=[
        Option("streamer", description="The streamer username you want to add the alert for", type=OptionType.STRING, required=True),
        Option("notification_channel", description="The channel to send the follow alerts in", type=OptionType.CHANNEL, required=True)
    ])
    @has_guild_permissions(administrator=True)
    async def addfollowalert(self, ctx: SlashInteraction, streamer, notification_channel):
        # Run checks on all the supplied arguments
        streamer_info = await self.check_streamer(username=streamer)
        if not streamer_info:
            raise BadArgument(f"Could not find twitch user {streamer}!")
        await self.check_channel_permissions(ctx, channel=notification_channel)

        #Checks done
        if isinstance(notification_channel, int): notification_channel = self.bot.get_channel(notification_channel)

        #Create file structure and subscriptions if necessary
        try:
            async with aiofiles.open("config/follows.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            callbacks = {}
        except JSONDecodeError:
            callbacks = {}
        
        if streamer not in callbacks.keys():
            callbacks[streamer] = {"channel_id": streamer_info["id"], "secret": await random_string_generator(21), "channels": {}}
            response = await self.bot.api_request("https://api.twitch.tv/helix/eventsub/subscriptions",
                json={
                    "type": "channel.follow",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": streamer_info["id"]
                    },
                    "transport": {
                        "method": "webhook",
                        "callback": f"{self.bot.auth['callback_url']}/callback/{streamer}",
                        "secret": callbacks[streamer]["secret"]
                    }
                }, method="post")
            if response.status not in [202, 409]:
                raise SubscriptionError(f"There was an error subscribing to the stream online eventsub. Please try again later. Error code: {response.status_code}")
            json1 = await response.json()
            callbacks[streamer]["subscription_id"] = json1["data"][0]["id"]
        callbacks[streamer]["channels"][str(ctx.guild.id)] = {"notif_channel_id": notification_channel.id}

        async with aiofiles.open("config/follows.json", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))

        embed = Embed(title="Successfully added new follow alert", color=self.bot.colour)
        embed.description = f"If you wish to utilize the block feature, authorize the user that you just setup [here]({self.bot.auth_url})"
        embed.add_field(name="Streamer", value=streamer, inline=True)
        embed.add_field(name="Notification Channel", value=notification_channel, inline=True)
        await ctx.send(embed=embed)

    @slash_command(description="Remove a follow notification alert", options=[Option("streamer", "The name of the streamer to be removed", type=OptionType.STRING, required=True)])
    @has_guild_permissions(administrator=True)
    async def delfollow(self, ctx, streamer: str):
        await self.callback_deletion(ctx, streamer)

    async def callback_deletion(self, ctx, streamer):
        try:
            async with aiofiles.open(f"config/follows.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            callbacks = {}
        except JSONDecodeError:
            callbacks = {}
        try:
            del callbacks[streamer]["channels"][str(ctx.guild.id)]
        except KeyError:
            embed = Embed(title="Error", description="<:red_tick:809191812337369118> Streamer not found for server", colour=self.bot.colour)
            await ctx.send(embed=embed)
            return
        if callbacks[streamer]["channels"] == {}:
            self.bot.log.info(f"Streamer {streamer} has no more alerts, purging")
            try:
                response = await self.bot.api_request(f"https://api.twitch.tv/helix/eventsub/subscriptions?id={callbacks[streamer]['subscription_id']}", method="delete")
                self.bot.log.info(f"Revoke request returned response code {response.status}")
            except KeyError:
                pass
            del callbacks[streamer]
        async with aiofiles.open(f"config/follows.json", "w") as f:
            await f.write(json.dumps(callbacks, indent=4))
        embed = Embed(title="Streamer Removed", description=f"Deleted alert for {streamer}", colour=self.bot.colour)
        return await ctx.send(embed=embed)


            
async def random_string_generator(str_size):
    return "".join(choice(ascii_letters) for _ in range(str_size))


def setup(bot):
    bot.add_cog(RecieverCommands(bot))