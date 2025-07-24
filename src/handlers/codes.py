import asyncio
import json
import re
from typing import Iterable, List

import aiohttp
import discord
import genshin.errors
from discord.ext import commands, tasks
from lxml import html
from sqlalchemy import select

from common import conf
from common.constants import Preferences
from common.db import session
from common.logging import logger
from datamodels.code_redemption import RedeemableCode
from datamodels.genshin_user import GenshinUser
from datamodels.guild_settings import GuildSettings, GuildSettingKey


CODE_REGEX = r"^ *[A-Za-z0-9]{8,20} *$"


class CodeScanner(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.start_up = False

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.start_up:
            self.poll.start()
            self.start_up = True

    @tasks.loop(minutes=15)
    async def poll(self):
        logger.info(f"Checking for new game codes")
        async with aiohttp.ClientSession() as http:
            games = {'GENSHIN': set(), 'STARRAIL': set(), 'ZZZ': set()}
            games['GENSHIN'].update([c async for c in self.get_codes_from_pockettactics('genshin')])
            games['STARRAIL'].update([c async for c in self.get_codes_from_pockettactics('hsr')])
            games['ZZZ'].update([c async for c in self.get_codes_from_pockettactics('zzz')])

        existing_codes = set(
            session.execute(select(RedeemableCode.code)).scalars()
        )

        await self.validateTokens()

        for game in games :
            if games[game].issubset(existing_codes):
                logger.info(f"\t{game} >>> No new codes found")
            else:
                new_codes = games[game] - existing_codes

                logger.info(f"\t{game} >>> New code is available: {new_codes}")

                for code in new_codes:
                    session.merge(RedeemableCode(code=code, working=True))

                for code in existing_codes - games[game]:
                    session.merge(RedeemableCode(code=code, working=False))

                session.commit()

                await self.send_notification(new_codes, game)
                await self.redeem(new_codes, game)
        logger.info(f"Code check completed")

    async def send_notification(self, codes: Iterable[str], game_name: str):
        embed = discord.Embed(
            title="New codes available",
            description="\n".join(
                f"[{code}](https://genshin.hoyoverse.com/en/gift?code={code})"
                for code in codes
            )
        )

        for code_channel in session.execute(
                select(GuildSettings).where(
                    GuildSettings.key == GuildSettingKey.CODE_CHANNEL
                )
        ).scalars():
            try:
                channel = await self.bot.fetch_channel(code_channel.value)
                code_role = session.get(
                    GuildSettings,
                    (code_channel.guild_id, GuildSettingKey.CODE_ROLE),
                )
                await channel.send(
                    content=f"\n<@&{code_role.value}>" if code_role else None,
                    embed=embed,
                )
            except Exception:
                logger.exception("Cannot send new code notifications")

    async def redeem(self, codes: Iterable[str], game_name: str):
        accounts: List[GenshinUser] = (
            session.execute(
                select(GenshinUser).where(GenshinUser.mihoyo_token.is_not(None))
            ).scalars().all()
        )

        match game_name:
            case 'GENSHIN': redeem_game = genshin.Game.GENSHIN
            case 'STARRAIL': redeem_game = genshin.Game.STARRAIL
            case 'ZZZ': redeem_game = genshin.Game.ZZZ

        for code in codes:
            queue = []
            for account in accounts:
                if not account.settings[Preferences.AUTO_REDEEM]:
                    continue
                logger.info(f"\t {game_name} >>> Redeeming code {code} for account {account.mihoyo_id}")
                queue.append(asyncio.create_task(account.client.redeem_code(code=code, game=redeem_game)))
                queue.append(asyncio.create_task(asyncio.sleep(5)))

            results = await asyncio.gather(*queue, return_exceptions=True)

            if results and isinstance(results[0], genshin.errors.RedemptionInvalid):
                session.merge(RedeemableCode(code=code, working=False))
                logger.info(f"\t {game_name} >>> Code {code} expired. Updating database")

            await asyncio.sleep(7)
            logger.info(f"\t {game_name} >>> Results: {results}")

        session.commit()

    async def get_codes_from_pockettactics(self, game):
        async with aiohttp.ClientSession() as session:
            match game:
                case 'genshin':
                    url = "https://www.pockettactics.com/genshin-impact/codes"
                case 'hsr':
                    url = "https://www.pockettactics.com/honkai-star-rail/codes"
                case 'zzz':
                    url = "https://www.pockettactics.com/zenless-zone-zero/codes"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'
            }
            async with session.get(url, headers=headers) as r:
                if r.status != 200:
                    return

                # Parse the HTML with lxml
                tree = html.fromstring(await r.text())

                # Find the desired elements
                content_div = tree.xpath('//div[@class="entry-content"]')
                found = False  # whether a block of valid codes have been found
                if content_div:
                    for ul in content_div[0].xpath('.//ul'):
                        for code in ul.xpath('.//strong | .//b'):
                            code_text = code.text_content().strip()
                            if re.match(CODE_REGEX, code_text):
                                found = True
                                yield code_text
                        if found:
                            break
                        for code in ul.xpath('.//b'):
                            code_text = code.text_content().strip()
                            if re.match(CODE_REGEX, code_text):
                                found = True
                                yield code_text
                        if found:
                            break
                    
    async def validateTokens(self):
        accounts: List[GenshinUser] = (
            session.execute(
                select(GenshinUser).where(GenshinUser.mihoyo_token.is_not(None))
            ).scalars().all()
        )

        for account in accounts:
            if not account.settings[Preferences.AUTO_REDEEM]:
                continue
        
        messages = []
        logger.info(f"\tValidating {account.mihoyo_id}")
        async for item in account.validate():
            messages += [f"{item} is valid for {account.mihoyo_id}"]
        logger.info(f"\t\t{messages}")
        session.merge(account)
        session.commit()

    def get_codes_from_text(self, data):
        """
        Supports extracting codes from the following format:
         - Line-by-line codes
         - JSON (from https://ataraxyaffliction.github.io/)
        """
        def parse_json(obj):
            return {item["code"] for item in obj}

        def parse_text(data):
            codes = set()
            for line in data.splitlines():
                if re.match(CODE_REGEX, line):
                    codes.add(line)
            return codes

        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            return parse_text(data)
        else:
            return parse_json(obj)
