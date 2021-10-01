from discord import Intents, Colour, Activity, ActivityType, Forbidden, HTTPException, Embed
from discord.ext import commands
from discord.utils import utcnow
from webserver import RecieverWebServer
from aiohttp import ClientSession
from asyncio import sleep
from systemd.daemon import notify, Notification
from systemd.journal import JournaldLogHandler
from json.decoder import JSONDecodeError
from time import time
import aiofiles
import logging
import json
from dislash import InteractionClient, ActionRow, Button, ButtonStyle
from dateutil import parser

class TwitchFollowManager(commands.Bot):
    def __init__(self):
        intents = Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned_or("t!"), intents=intents, activity=Activity(type=ActivityType.listening, name="the silence of the void"))

        self.log = logging.getLogger("FollowChecker")
        self.log.setLevel(logging.INFO)

        jhandler = JournaldLogHandler()
        jhandler.setLevel(logging.INFO)
        jhandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(jhandler)

        self.slash = InteractionClient(self, test_guilds=[749646865531928628])
        self.web_server = RecieverWebServer(self)
        self.loop.run_until_complete(self.web_server.start())

        self.load_extension(f"cogs.cog")
        self.load_extension(f"cogs.error_listener")
        self.colour = Colour.from_rgb(128, 0, 128)
        with open("config/auth.json") as f:
            self.auth = json.load(f)
        self.token = self.auth["bot_token"]
        self._uptime = time()
        self.aSession = None
        self.auth_url = f"https://id.twitch.tv/oauth2/authorize?client_id={self.auth['client_id']}&redirect_uri={self.auth['callback_url']}/authorize&force_verify=true&response_type=code&scope=user:manage:blocked_users"

    async def close(self):
        notify(Notification.STOPPING)
        await self.aSession.close()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_connect(self):
        self.aSession = ClientSession() #Make the aiohttp session asap

    @commands.Cog.listener()
    async def on_ready(self):
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")
        notify(Notification.READY)

    async def api_request(self, url, session=None, method="get", **kwargs):
        session = session or self.aSession
        response = await session.request(method=method, url=url, headers={"Authorization": f"Bearer {self.auth.get('access_token', '')}", "Client-Id": self.auth["client_id"]}, **kwargs)
        if response.status == 401: #Reauth pog
            reauth = await session.post(url=f"https://id.twitch.tv/oauth2/token?client_id={self.auth['client_id']}&client_secret={self.auth['client_secret']}&grant_type=client_credentials")
            if reauth.status == 401:
                self.log.critical("Well somethin fucked up. Check your credentials!")
                await self.close()
            reauth_data = await reauth.json()
            self.auth["access_token"] = reauth_data["access_token"]
            async with aiofiles.open("config/auth.json", "w") as f:
                await f.write(json.dumps(self.auth, indent=4))
            response = await session.request(method=method, url=url, headers={"Authorization": f"Bearer {self.auth['access_token']}", "Client-Id": self.auth["client_id"]}, **kwargs)
            return response
        else:
            return response

    async def user_api_request(self, url, user_id, session=None, method="get", **kwargs):
        try:
            async with aiofiles.open("config/user_authorization.json",) as f:
                user_authorization = json.loads(await f.read())
        except FileNotFoundError:
            return
        except JSONDecodeError:
            pass
        session = session or self.aSession
        response = await session.request(method=method, url=url, headers={"Authorization": f"Bearer {user_authorization[user_id]['access_token']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        if response.status == 401: #Reauth pog
            reauth = await session.post(url=f"https://id.twitch.tv/oauth2/token?refresh_token={user_authorization[user_id]['refresh_token']}&client_id={self.auth['client_id']}&client_secret={self.auth['client_secret']}&grant_type=refresh_token")
            if reauth.status == 401:
                self.log.critical("Well somethin fucked up. Check your credentials!")
                return
            reauth_data = await reauth.json()
            user_authorization["access_token"] = reauth_data["access_token"]
            user_authorization["refresh_token"] = reauth_data["refresh_token"]
            self.log.info(f"Got new token for {user_id}")
            async with aiofiles.open("config/user_authorization.json", "w") as f:
                await f.write(json.dumps(user_authorization, indent=4))
            return await session.request(method=method, url=url, headers={"Authorization": f"Bearer {user_authorization[user_id]['access_token']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        else:
            return response

    async def new_follower(self, channel, data):
        await sleep(10)
        try:
            async with aiofiles.open("config/follows.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        except JSONDecodeError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return

        still_following = False
        r = await self.api_request(f"https://api.twitch.tv/helix/users/follows?from_id={data['event']['user_id']}&to_id={data['event']['broadcaster_user_id']}")
        rj = await r.json()
        if rj["total"] > 0:
            still_following = True

        button_row = ActionRow(
            Button(
                style=ButtonStyle.red,
                label="Block User",
                custom_id=f"{data['event']['broadcaster_user_id']}/{data['event']['user_id']}"
            )
        )
        user_response = await self.api_request(f"https://api.twitch.tv/helix/users?id={data['event']['user_id']}")
        self.log.info(await user_response.json())
        user = (await user_response.json())["data"][0]
        created_at_timestamp = int(parser.parse(user["created_at"]).timestamp())


        embed = Embed(title="New Follower", colour=11537322, timestamp=utcnow())
        embed.add_field(name="Broadcaster", value=data["event"]["broadcaster_user_login"])
        embed.add_field(name="Follower", value=user["login"])
        embed.add_field(name="Account Created", value=f"<t:{created_at_timestamp}:R>")
        embed.add_field(name="Mod Card", value=f"[Link](https://www.twitch.tv/popout/{data['event']['broadcaster_user_login']}/viewercard/{user['login']})")
        embed.add_field(name="Still following?", value="Yes" if still_following else "No")
        embed.set_footer(text=f"Follower User ID: {user['id']}")
        for data in callbacks[channel]["channels"].values():
            c = self.get_channel(data["notif_channel_id"])
            if c is not None:
                try:
                    await c.send(embed=embed, components=[button_row])
                except Forbidden:
                    pass
                except HTTPException:
                    pass





bot = TwitchFollowManager()
bot.run(bot.token)
