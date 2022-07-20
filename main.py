from disnake import Intents, Colour, Activity, ActivityType, Forbidden, HTTPException, Embed, ButtonStyle, ApplicationCommandInteraction, PartialEmoji, Emoji
from disnake.ui import View, Button
from disnake.ext import commands
from disnake.utils import utcnow
from webserver import RecieverWebServer
from aiohttp import ClientSession
from asyncio import sleep, iscoroutinefunction, Queue
from json.decoder import JSONDecodeError
from time import time
import aiofiles
import sys
import logging
import json
from dateutil import parser
from typing import Optional, Union, Callable

class ButtonCallback(Button):
    def __init__(
        self,
        *,
        style: ButtonStyle = ButtonStyle.secondary,
        label: Optional[str] = None,
        disabled: bool = False,
        custom_id: Optional[str] = None,
        callback: Optional[Callable] = None,
        url: Optional[str] = None,
        emoji: Optional[Union[str, Emoji, PartialEmoji]] = None,
        row: Optional[int] = None,
    ):
        super().__init__(style=style, label=label, disabled=disabled, custom_id=custom_id, url=url, emoji=emoji, row=row)
        if not iscoroutinefunction(callback):
            raise TypeError("Callback must be a coroutine!")
        self.callback = callback

class TwitchFollowManager(commands.InteractionBot):
    def __init__(self):
        intents = Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, activity=Activity(type=ActivityType.listening, name="the silence of the void"))

        self.log = logging.getLogger("FollowChecker")
        self.log.setLevel(logging.INFO)

        shandler = logging.StreamHandler(sys.stdout)
        shandler.setLevel(logging.DEBUG)
        shandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.log.addHandler(shandler)

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
        self.queue = Queue(maxsize=0)
        self.worker = self.loop.create_task(self._worker())

    async def close(self):
        if not self.aSession.closed:
            await self.aSession.close()
        self.log.info("Shutting down...")
        await super().close()

    @commands.Cog.listener()
    async def on_connect(self):
        self.aSession = ClientSession() #Make the aiohttp session asap

    @commands.Cog.listener()
    async def on_ready(self):
        self.log.info(f"------ Logged in as {self.user.name} - {self.user.id} ------")

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
            async with aiofiles.open("config/user_authorization.json") as f:
                user_authorization = json.loads(await f.read())
        except FileNotFoundError:
            return
        except JSONDecodeError:
            return
        session = session or self.aSession
        response = await session.request(method=method, url=url, headers={"Authorization": f"Bearer {user_authorization[user_id]['access_token']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        if response.status == 401: #Reauth pog
            reauth = await session.post(url=f"https://id.twitch.tv/oauth2/token?refresh_token={user_authorization[user_id]['refresh_token']}&client_id={self.auth['client_id']}&client_secret={self.auth['client_secret']}&grant_type=refresh_token")
            if reauth.status == 401:
                self.log.critical("Well somethin fucked up. Check your credentials!")
                return
            reauth_data = await reauth.json()
            user_authorization[user_id]["access_token"] = reauth_data["access_token"]
            user_authorization[user_id]["refresh_token"] = reauth_data["refresh_token"]
            self.log.info(f"Got new token for {user_id}")
            async with aiofiles.open("config/user_authorization.json", "w") as f:
                await f.write(json.dumps(user_authorization, indent=4))
            return await session.request(method=method, url=url, headers={"Authorization": f"Bearer {user_authorization[user_id]['access_token']}", "Client-Id": self.auth["client_id"]}, **kwargs)
        else:
            return response

    async def _worker(self):
        self.log.debug("Queue Worker Started")
        while not self.is_closed():
            item = await self.queue.get()
            self.log.debug(f"Recieved event! {type(item).__name__}")
            await self.new_follower(item)
            self.log.debug(f"Finished task {type(item).__name__}")
            self.queue.task_done()

    async def new_follower(self, data: dict):
        await sleep(10)
        try:
            async with aiofiles.open("config/follows.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            self.log.error("Failed to read follows config file!")
            return
        except JSONDecodeError:
            self.log.error("Failed to read follows config file!")
            return

        still_following = False
        r = await self.api_request(f"https://api.twitch.tv/helix/users/follows?from_id={data['event']['user_id']}&to_id={data['event']['broadcaster_user_id']}")
        rj = await r.json()
        if rj["total"] > 0:
            still_following = True

        class BlockView(View):
            def __init__(self, data: dict):
                super().__init__()
                self.add_item(Button(style=ButtonStyle.red, label="Block User", custom_id=f"{data['event']['broadcaster_user_id']}/{data['event']['user_id']}"))

        user_response = await self.api_request(f"https://api.twitch.tv/helix/users?id={data['event']['user_id']}")
        user = (await user_response.json())["data"][0]
        created_at_timestamp = int(parser.parse(user["created_at"]).timestamp())


        embed = Embed(title="New Follower", colour=11537322, timestamp=utcnow())
        embed.add_field(name="Broadcaster", value=data["event"]["broadcaster_user_login"])
        embed.add_field(name="Follower", value=user["login"])
        embed.add_field(name="Account Created", value=f"<t:{created_at_timestamp}:R>")
        embed.add_field(name="Mod Card", value=f"[Link](https://www.twitch.tv/popout/{data['event']['broadcaster_user_login']}/viewercard/{user['login']})")
        embed.add_field(name="Still following after 10s?", value="Yes" if still_following else "No")
        embed.set_footer(text=f"Follower User ID: {user['id']}")
        view = BlockView(data)
        for config_channels in callbacks[data['event']['broadcaster_user_login']]["channels"].values():
            c = self.get_channel(config_channels["notif_channel_id"])
            if c is not None:
                try:
                    await c.send(embed=embed, view=view)
                except Forbidden:
                    pass
                except HTTPException:
                    pass





bot = TwitchFollowManager()
bot.run(bot.token)
