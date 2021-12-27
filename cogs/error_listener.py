from disnake import ApplicationCommandInteraction
from disnake.errors import Forbidden
from disnake.ext import commands
from traceback import format_exc, format_exception
from cogs.cog import SubscriptionError
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..main import TwitchFollowManager

class ErrorListener(commands.Cog):
    def __init__(self, bot):
        self.bot: TwitchFollowManager = bot
        super().__init__()

    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs):
        channel = self.bot.get_channel(763351494685884446)
        self.bot.log.error(format_exc())
        await channel.send(f"```python\n{format_exc()[:1982]}\n```")

    @commands.Cog.listener()
    async def on_slash_command_error(self, ctx: ApplicationCommandInteraction, exception):
        if isinstance(exception, (commands.MissingPermissions, commands.NotOwner, commands.MissingRole, commands.CheckFailure, commands.BadArgument, SubscriptionError)):
            return await ctx.send(content=f"<:red_tick:809191812337369118> {exception}")
        if isinstance(exception, Forbidden):
            return await ctx.send("The bot does not have access to send messages! Because I can send this error message but not the response to the command")

        if await self.bot.is_owner(ctx.author):
            err_msg = f"<:red_tick:809191812337369118> There was an error executing this command.\n`{type(exception).__name__}: {exception}`"
        else:
            err_msg = "<:red_tick:809191812337369118> There was an error executing this command."
        await ctx.send(err_msg)

        exc = ''.join(format_exception(type(exception), exception, exception.__traceback__))
        self.bot.log.error(f"Ignoring exception in command {ctx.application_command.name}:\n{exc}")
        error_str = str(exc).replace("\\", "\\\\")[:1900]
        channel = self.bot.get_channel(763351494685884446)
        if channel is not None:
            try:
                await channel.send(f"```python\nException in command {ctx.application_command.name}\n{error_str}\n```")
            except Forbidden:
                pass

def setup(bot):
    bot.add_cog(ErrorListener(bot))