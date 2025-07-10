import asyncio
from typing import List

import discord
import genshin.errors
import re
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
        codes: Option(str, "Codes separated by commas or spaces", required=False),
        target: Option(str, "UID or 'all' for everyone", name="for", default=False),
    ):
        logger.info(f"{ctx.author.id} used /redeem command")
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
                logger.info(f"\t{ctx.author.id} is not registered")
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

        game = game.upper()
        match game:
            case "HSR": redeem_for = genshin.Game.STARRAIL
            case "ZZZ": redeem_for = genshin.Game.ZZZ
            case _: redeem_for = genshin.Game.GENSHIN

        game_codes = set(re.sub(r'(?![a-zA-Z0-9]+).',',',codes).split(","))
        game_codes.discard('')

        if len(game_codes) < 1:
            await ctx.respond(f"No codes entered, doing nothing")
            return
        if len(game_codes) > 10:
            await ctx.respond(f"Too many codes")
            logger.info(f"\tUser input >10 codes")
            return

        await ctx.defer()
        embeds = []

        for code in game_codes:
            code = code.strip().upper()
            embed = discord.Embed(
                description=f"{Emoji.LOADING} Redeeming {game} code {code}... "
            )
            embeds.append(embed)
            await ctx.edit(embeds=embeds)
            already_claimed = 0
            redeemed = 0

            try:
                for i, account in enumerate(accounts):
                    embed.description = (
                        f"{Emoji.LOADING} Redeeming {game} code {code}... {i}/{len(accounts)}"
                    )
                    await ctx.edit(embeds=embeds)
                    gs = account.client
                    logger.info(f"\tRedeeming {code} for {game} for {account.mihoyo_id}")

                    try:
                        if target_uid:
                            await gs.redeem_code(code, game=redeem_for, uid=target_uid)
                        else:
                            await gs.redeem_code(code, game=redeem_for)
                        redeemed += 1
                    except genshin.errors.InvalidCookies as e:
                        # account.mihoyo_token = None
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
                        logger.info(f"\t\t{ctx.author.id} expired cookie_token for {account.mihoyo_id}: {e.retcode}")
                        logger.info(f"\t\t{ctx.author.id} attempt to renew for {account.mihoyo_id}")
                        messages = []
                        async for item in account.validate():
                            messages += [f":white_check_mark: {item} is valid"]
                            await ctx.edit(
                                embed=discord.Embed(
                                    description="\n".join(
                                        messages + [Emoji.LOADING + " verifying..."]
                                    )
                                )
                            )
                        session.merge(account)
                        session.commit()
                    except genshin.errors.GenshinException as e:
                        if e.retcode == -2017 or e.retcode == -2018:
                            already_claimed += 1
                            logger.exception(f"\t\t{code} is already claimed for {account.mihoyo_id}")
                        elif e.retcode == -2004:
                            logger.exception(f"\t\t{code} is not valid")
                        else:
                            logger.exception(f"\t\t{code} can't be claimed: {e.retcode}")
                        break

                embed.description = f"Redeemed {game} code {code} for {redeemed} accounts."
                if already_claimed:
                    embed.description += (
                        f"\n{already_claimed} accounts already claimed this code."
                    )
            except genshin.errors.GenshinException as e:
                if e.retcode == -2001:
                    embed.description = f"Code {code} has expired."
                    logger.exception(f"\t\t{code} has already expired")
                elif e.retcode == -2003 or e.retcode == -2004:
                    embed.description = f"{code} is not valid."
                    logger.exception(f"\t\t{code} is not valid")
                else:
                    logger.exception(f"\t\t{code} can't be claimed: {e.retcode}")
                break

            await ctx.edit(embeds=embeds)
            await asyncio.sleep(7)
        logger.info(f"{ctx.author.id} end of /redeem attempt")