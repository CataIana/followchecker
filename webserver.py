from json.decoder import JSONDecodeError
from aiohttp import web
import json
import hmac
import hashlib
import aiofiles

class RecieverWebServer():
    def __init__(self, bot):
        self.bot = bot
        self.port = 18276
        self.web_server = web.Application()
        self.web_server.add_routes([web.route('*', '/callback/{channel}', self._reciever)])
        self.web_server.add_routes([web.route('*', '/authorize', self._authorize)])

    async def start(self):
        runner = web.AppRunner(self.web_server)
        await runner.setup()
        await web.TCPSite(runner, host="localhost", port=self.port).start()
        self.bot.log.info(f"Webserver running on localhost:{self.port}")
        return self.web_server

    async def _reciever(self, request):
        await self.bot.wait_until_ready()
        channel = request.match_info["channel"]
        self.bot.log.info(f"{request.method} from {channel}")
        if request.method == 'POST':
            return await self.post_request(request, channel)
        return web.Response(status=404)
    
    async def _authorize(self, request):
        code = request.query.get("code", None)
        if code is None:
            return web.Response(status=400)
        response = await self.bot.aSession.post(f"https://id.twitch.tv/oauth2/token?client_id={self.bot.auth['client_id']}&client_secret={self.bot.auth['client_secret']}&code={code}&grant_type=authorization_code&redirect_uri={self.bot.auth['callback_url']}/authorize")
        rj = await response.json()
        try:
            async with aiofiles.open("config/user_authorization.json") as f:
                user_authorization = json.loads(await f.read())
        except FileNotFoundError:
            user_authorization = {}
        except JSONDecodeError:
            user_authorization = {}

        user_response = await self.bot.aSession.get("https://api.twitch.tv/helix/users", headers={"Client-Id": self.bot.auth["client_id"], "Authorization": f"Bearer {rj['access_token']}"})
        user_json = await user_response.json()
        user_authorization[user_json['data'][0]['id']] = {"access_token": rj["access_token"], "refresh_token": rj["refresh_token"]}
        async with aiofiles.open("config/user_authorization.json", "w") as f:
            await f.write(json.dumps(user_authorization, indent=4))
        
        return web.Response(status=200, text="You may now close this tab")

    async def verify_request(self, request, secret):
        try:
            async with aiofiles.open("cache/notifcache.cache") as f:
                notifcache = json.loads(await f.read())
        except FileNotFoundError:
            notifcache = []
        except json.decoder.JSONDecodeError:
            notifcache = []

        try:
            message_id = request.headers["Twitch-Eventsub-Message-Id"]
            timestamp = request.headers["Twitch-Eventsub-Message-Timestamp"]
            signature = request.headers['Twitch-Eventsub-Message-Signature']
        except KeyError as e:
            self.bot.log.info(f"Request Denied. Missing Key {e}")
            return False
        if message_id in notifcache:
            return None

        hmac_message = message_id.encode("utf-8") + timestamp.encode("utf-8") + await request.read()
        h = hmac.new(secret.encode("utf-8"), hmac_message, hashlib.sha256)
        expected_signature = f"sha256={h.hexdigest()}"
        self.bot.log.debug(f"Timestamp: {timestamp}")
        self.bot.log.debug(f"Expected: {expected_signature}. Receieved: {signature}")
        if signature != expected_signature:
            return False
        notifcache.append(message_id)
        if len(notifcache) > 10: notifcache = notifcache[1:]
        async with aiofiles.open("cache/notifcache.cache", "w") as f:
            await f.write(json.dumps(notifcache, indent=4))
        return True
            

    async def post_request(self, request, channel):
        try:
            async with aiofiles.open("config/follows.json") as f:
                callbacks = json.loads(await f.read())
        except FileNotFoundError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        except JSONDecodeError:
            self.bot.log.error("Failed to read title callbacks config file!")
            return
        if channel not in callbacks.keys():
            self.bot.log.info(f"Request for {channel} not found")
            return web.Response(status=404)

        verified = await self.verify_request(request, callbacks[channel]["secret"])
        if verified == False:
            self.bot.log.info("Unverified request, aborting")
            return web.Response(status=400)
        elif verified == None:
            self.bot.log.info("Already sent code, ignoring")
            return web.Response(status=202)
        try:
            mode = request.headers["Twitch-Eventsub-Message-Type"]
        except KeyError:
            self.bot.log.info("Missing required parameters")
            return web.Response(status=400)
        data = await request.json()
        
        if mode == "webhook_callback_verification": #Initial Verification of Subscription
            self.bot.log.info(f"Subscription confirmed for {channel}")
            challenge = data['challenge']
            return web.Response(status=202, text=challenge)
        elif mode == "authorization_revoked":
            self.bot.log.critical(f"Authorization Revoked for {channel}!")
            return web.Response(status=202)
        elif mode == "notification":
            self.bot.log.info(f"Notification for {channel}")
            return await self.notification(channel, data)
        else:
            self.bot.log.info("Unknown mode")
        return web.Response(status=404)

    async def notification(self, channel, data):
        await self.bot.new_follower(channel, data)
        return web.Response(status=202)