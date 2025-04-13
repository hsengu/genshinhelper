import asyncio
from typing import List

import discord
import genshin.errors
from discord import Option, ApplicationContext
from discord.ext import commands
from sqlalchemy import select

from common import guild_level
from common.constants import Emoji
from common.db import session
from common.logging import logger
from datamodels.genshin_user import GenshinUser
from datamodels.uid_mapping import UidMapping


class RedeemCodes(commands.Cog):
    def __init__(self, bot: discord.Bot = None):
        self.bot = bot

    @commands.slash_command(
        description="Redeems HoYo game codes",
        guild_ids=guild_level.get_guild_ids(level=3),
    )
    async def redeem(
        self,
        ctx: ApplicationContext,
        game: Option(str, "Game to redeem for (pick 1, default is genshin): genshin,hsr,zzz", name="game", default="genshin", required=False),
        codes: Option(str, "Codes separated by commas", required=False),
        target: Option(str, "UID or 'all' for everyone", name="for", default=False),
    ):
        target: str = target or "all"
        if target not in ["all", "everyone"] and not target.isdigit():
            await ctx.respond(f'Enter a specific UID or "all" for everyone')
            return

        target_uid = None
        if target.isdigit():
            target_uid = int(target)
            uidmapping = session.get(UidMapping, (target_uid,))
            if not uidmapping:
                await ctx.respond(f"UID not registered with this bot")
                return
            accounts: List[GenshinUser] = (
                session.execute(
                    select(GenshinUser).where(
                        GenshinUser.mihoyo_token.is_not(None),
                        GenshinUser.mihoyo_id == uidmapping.mihoyo_id,
                    )
                )
                .scalars()
                .all()
            )
        else:
            accounts: List[GenshinUser] = (
                session.execute(
                    select(GenshinUser).where(GenshinUser.mihoyo_token.is_not(None))
                )
                .scalars()
                .all()
            )

        redeem_for = ""
        
        match game:
            case "hsr": redeem_for = "hkrpg"
            case "zzz": redeem_for = "nap"
            case _: redeem_for = "genshin"

        game_codes = set(codes.split(","))

        if len(game_codes) < 1:
            await ctx.respond(f"No codes entered, doing nothing")
            return
        if len(game_codes) > 10:
            await ctx.respond(f"Too many codes")
            return

        await ctx.defer()
        embeds = []

        for code in game_codes:
            code = code.strip().upper()
            embed = discord.Embed(
                description=f"{Emoji.LOADING} Redeeming {redeem_for} code {code}... "
            )
            embeds.append(embed)
            await ctx.edit(embeds=embeds)
            already_claimed = 0
            redeemed = 0

            try:
                for i, account in enumerate(accounts):
                    embed.description = (
                        f"{Emoji.LOADING} Redeeming code {code}... {i}/{len(accounts)}"
                    )
                    await ctx.edit(embeds=embeds)
                    gs = account.client

                    try:
                        if target_uid:
                            await gs.redeem_code(code, game=redeem_for, uid=target_uid)
                        else:
                            await gs.redeem_code(code, game=redeem_for)
                        redeemed += 1
                    except genshin.errors.InvalidCookies:
                        account.mihoyo_token = None
                        session.merge(account)
                        session.commit()
                        user = await self.bot.fetch_user(account.discord_id)
                        dm_channel = await self.bot.create_dm(user)
                        await dm_channel.send(
                            embed=discord.Embed(
                                title=":warning: Account Access Failure",
                                description=f"Your cookie_token has expired for Hoyolab ID {account.mihoyo_id}.\n"
                                            f"This may be because you have changed your password recently.\n"
                                            f"Please register again if you want to continue using the bot."
                            )
                        )
                    except genshin.errors.GenshinException as e:
                        if e.retcode == -2017:
                            already_claimed += 1
                        elif e.retcode == -2018:
                            already_claimed += 1
                        else:
                            raise e

                embed.description = f"Redeemed code {code} for {redeemed} accounts."
                if already_claimed:
                    embed.description += (
                        f"\n{already_claimed} accounts already claimed this code."
                    )
            except genshin.errors.GenshinException as e:
                if e.retcode == -2001:
                    embed.description = f"Code {code} has expired."
                elif e.retcode == -2003:
                    embed.description = f"Code {code} is invalid."
                else:
                    logger.exception(f"Code can't be claimed: {e.retcode}")
                    raise e

            await ctx.edit(embeds=embeds)
            await asyncio.sleep(7)
