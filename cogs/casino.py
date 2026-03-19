import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, time, random, asyncio
from datetime import time as dt_time, timezone
from utils import load_guild_json, save_guild_json

DATA_FILE = "users.json"
ECONOMY_CONFIG = "economy_config.json"
CASINO_CONFIG = "casino_config.json"

# ==========================================
# ДОПОМІЖНІ ФУНКЦІЇ КАЗИНО
# ==========================================

def get_casino_config(guild_id: int):
    config = load_guild_json(guild_id, CASINO_CONFIG)
    if not config:
        config = {
            "bank": 0,
            "max_bet": 1000
        }
        save_guild_json(guild_id, CASINO_CONFIG, config)
    return config

def update_activity(user_data):
    """Оновлює час останньої активності в казино"""
    user_data["last_casino_action"] = int(time.time())

def process_bet(user_data, casino_config, bet_amount: int) -> bool:
    """Перевіряє, чи може гравець зробити ставку, і списує фішки"""
    if bet_amount <= 0: return False
    if bet_amount > casino_config.get("max_bet", 1000): return False
    if user_data.get("chips", 0) < bet_amount: return False
    
    if user_data.get("restricted_casino"): return False

    user_data["chips"] -= bet_amount
    update_activity(user_data)
    return True

# ==========================================
# РУЛЕТКА: МОДАЛЬНЕ ВІКНО ДЛЯ СТАВКИ
# ==========================================

class RouletteBetModal(discord.ui.Modal):
    def __init__(self, bet_type: str, bet_value: str, payout_mult: int, cog: commands.Cog):
        super().__init__(title=f"Ставка: {bet_value}")
        self.bet_type = bet_type
        self.bet_value = bet_value
        self.payout_mult = payout_mult
        self.cog = cog

        self.bet_input = discord.ui.TextInput(
            label="Сума ставки (у фішках)",
            placeholder="Наприклад: 10",
            required=True,
            style=discord.TextStyle.short
        )
        self.add_item(self.bet_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet_amount = int(self.bet_input.value)
        except ValueError:
            return await interaction.response.send_message("Введіть ціле число!", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        casino_conf = get_casino_config(guild_id)
        
        uid = str(interaction.user.id)
        if uid not in data: data[uid] = {}
        user_data = data[uid]

        if bet_amount > casino_conf.get("max_bet", 1000):
            return await interaction.response.send_message(f"Максимальна ставка: {casino_conf.get('max_bet')} фішок.", ephemeral=True)

        if not process_bet(user_data, casino_conf, bet_amount):
            return await interaction.response.send_message("У вас недостатньо фішок для цієї ставки!", ephemeral=True)

        casino_conf["bank"] += bet_amount

        await interaction.response.defer()

        # === КРУТИМО РУЛЕТКУ ===
        result_num = random.randint(0, 36)
        
        potential_payout = bet_amount * self.payout_mult
        if casino_conf["bank"] < potential_payout * 2:
            if random.random() < 0.15: 
                result_num = 0

        is_red = result_num in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
        is_black = result_num != 0 and not is_red
        is_even = result_num != 0 and result_num % 2 == 0
        is_odd = result_num != 0 and result_num % 2 != 0
        
        color_emoji = "🟢" if result_num == 0 else ("🔴" if is_red else "⬛")

        win = False
        if self.bet_type == "color":
            if self.bet_value == "Червоне" and is_red: win = True
            elif self.bet_value == "Чорне" and is_black: win = True
        elif self.bet_type == "evenodd":
            if self.bet_value == "Парне" and is_even: win = True
            elif self.bet_value == "Непарне" and is_odd: win = True
        elif self.bet_type == "dozen":
            if self.bet_value == "1-12" and 1 <= result_num <= 12: win = True
            elif self.bet_value == "13-24" and 13 <= result_num <= 24: win = True
            elif self.bet_value == "25-36" and 25 <= result_num <= 36: win = True
        elif self.bet_type == "exact":
            if str(result_num) == self.bet_value: win = True

        anim_msg = await interaction.followup.send(f"🎰 Рулетка крутиться... 🎲", wait=True)
        await asyncio.sleep(2)

        if win:
            payout = bet_amount * self.payout_mult
            user_data["chips"] += payout
            casino_conf["bank"] -= payout
            embed = discord.Embed(title=f"Випало: {color_emoji} {result_num}", description=f"🎉 **ВИГРАШ!** Ви ставили на {self.bet_value}.\nВи отримали `{payout}` фішок!", color=0x2ecc71)
        else:
            embed = discord.Embed(title=f"Випало: {color_emoji} {result_num}", description=f"💀 **ПРОГРАШ.** Ви ставили на {self.bet_value}.\nСтавка `{bet_amount}` фішок згоріла.", color=0xe74c3c)

        embed.set_footer(text=f"Ваші фішки: {user_data['chips']}")
        
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CASINO_CONFIG, casino_conf)
        
        await anim_msg.edit(content=interaction.user.mention, embed=embed)

# ==========================================
# РУЛЕТКА: UI ЕЛЕМЕНТИ
# ==========================================

class RouletteDozensSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [
            discord.SelectOption(label="1-12 (Перша дюжина)", value="1-12", description="Виплата 3x"),
            discord.SelectOption(label="13-24 (Друга дюжина)", value="13-24", description="Виплата 3x"),
            discord.SelectOption(label="25-36 (Третя дюжина)", value="25-36", description="Виплата 3x")
        ]
        super().__init__(placeholder="Ставка на діапазон (виплата 3x)", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RouletteBetModal("dozen", self.values[0], 3, self.cog))

class RouletteExactLowSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [discord.SelectOption(label=f"Число {i}", value=str(i), description="Виплата 36x") for i in range(0, 19)]
        super().__init__(placeholder="Поставити на точне число 0–18 (виплата 36x)", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RouletteBetModal("exact", self.values[0], 36, self.cog))

class RouletteExactHighSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [discord.SelectOption(label=f"Число {i}", value=str(i), description="Виплата 36x") for i in range(19, 37)]
        super().__init__(placeholder="Ставка на точне число 19–36 (виплата 36x)", min_values=1, max_values=1, options=options, row=3)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RouletteBetModal("exact", self.values[0], 36, self.cog))

class RouletteView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(RouletteDozensSelect(cog))
        self.add_item(RouletteExactLowSelect(cog))
        self.add_item(RouletteExactHighSelect(cog))

    @discord.ui.button(label="Червоне", style=discord.ButtonStyle.danger, row=0)
    async def btn_red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RouletteBetModal("color", "Червоне", 2, self.cog))

    @discord.ui.button(label="Чорне", style=discord.ButtonStyle.secondary, row=0)
    async def btn_black(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RouletteBetModal("color", "Чорне", 2, self.cog))

    @discord.ui.button(label="Парне", style=discord.ButtonStyle.primary, row=0)
    async def btn_even(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RouletteBetModal("evenodd", "Парне", 2, self.cog))

    @discord.ui.button(label="Непарне", style=discord.ButtonStyle.primary, row=0)
    async def btn_odd(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RouletteBetModal("evenodd", "Непарне", 2, self.cog))


# ==========================================
# ОСНОВНИЙ КОГ КАЗИНО
# ==========================================

class CasinoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_cashout_loop.start()
        self.casino_bank_sync_loop.start()

    def cog_unload(self):
        self.auto_cashout_loop.cancel()
        self.casino_bank_sync_loop.cancel()


    @tasks.loop(minutes=5)
    async def auto_cashout_loop(self):
        """Кожні 5 хвилин перевіряє АФК гравців і конвертує їх фішки назад в AC"""
        if not os.path.exists("server_data"): return
        current_time = int(time.time())
        
        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                data = load_guild_json(guild_id, DATA_FILE)
                updated = False
                
                for uid, user in data.items():
                    chips = user.get("chips", 0)
                    last_action = user.get("last_casino_action", 0)
                    
                    if chips > 0 and (current_time - last_action) > 1800:
                        ac_amount = chips * 90
                        user["chips"] = 0
                        user["balance"] = user.get("balance", 0) + ac_amount
                        updated = True
                        
                        guild = self.bot.get_guild(guild_id)
                        if guild:
                            member = guild.get_member(int(uid))
                            if member:
                                try:
                                    await member.send(f"🎰 Ви не грали в казино більше 30 хвилин. Ваші `{chips}` фішок були автоматично обміняні на `{ac_amount} AC` (Курс 1:90).")
                                except: pass
                                
                if updated:
                    save_guild_json(guild_id, DATA_FILE, data)
            except Exception as e:
                pass

    @tasks.loop(time=dt_time(hour=1, minute=0, tzinfo=timezone.utc))
    async def casino_bank_sync_loop(self):
        """О 3-й ночі банк казино синхронізується з казною сервера (забирає рівно 10% від серверної казни)"""
        if not os.path.exists("server_data"): return
        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                eco_conf = load_guild_json(guild_id, ECONOMY_CONFIG)
                cas_conf = get_casino_config(guild_id)
                
                server_bank = eco_conf.get("server_bank", 0)
                target_casino_bank = int(server_bank * 0.10)
                
                current_casino_bank = cas_conf.get("bank", 0)
                
                if current_casino_bank > target_casino_bank:
                    surplus = current_casino_bank - target_casino_bank
                    eco_conf["server_bank"] += surplus
                elif current_casino_bank < target_casino_bank:
                    deficit = target_casino_bank - current_casino_bank
                    eco_conf["server_bank"] -= deficit
                    
                cas_conf["bank"] = target_casino_bank
                
                save_guild_json(guild_id, ECONOMY_CONFIG, eco_conf)
                save_guild_json(guild_id, CASINO_CONFIG, cas_conf)
                
            except Exception as e:
                pass

    @auto_cashout_loop.before_loop
    @casino_bank_sync_loop.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

    # === КАСА / ОБМІННИК ===

    @app_commands.command(name="chips_buy", description="Купити фішки казино (Курс 1 фішка = 100 AC)")
    @app_commands.guild_only()
    async def buy_chips(self, interaction: discord.Interaction, amount: int):
        if amount <= 0: return await interaction.response.send_message("Кількість має бути більше 0.", ephemeral=True)
        
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        uid = str(interaction.user.id)
        if uid not in data: data[uid] = {}
        user = data[uid]
        
        cost = amount * 100
        if user.get("balance", 0) < cost:
            return await interaction.response.send_message(f"Недостатньо AC. Потрібно `{cost} AC`.", ephemeral=True)
            
        user["balance"] -= cost
        user["chips"] = user.get("chips", 0) + amount
        update_activity(user)
        
        conf = get_casino_config(guild_id)
        conf["bank"] += amount 
        
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CASINO_CONFIG, conf)
        
        await interaction.response.send_message(f"Ви купили `{amount}` фішок за `{cost} AC`. Хай щастить!", ephemeral=True)

    @app_commands.command(name="chips_sell", description="Продати фішки (Курс 1 фішка = 90 AC)")
    @app_commands.guild_only()
    async def sell_chips(self, interaction: discord.Interaction, amount: int):
        if amount <= 0: return await interaction.response.send_message("Кількість має бути більше 0.", ephemeral=True)
        
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        uid = str(interaction.user.id)
        user = data.get(uid, {})
        
        if user.get("chips", 0) < amount:
            return await interaction.response.send_message(f"У вас немає стільки фішок.", ephemeral=True)
            
        revenue = amount * 90
        user["chips"] -= amount
        user["balance"] = user.get("balance", 0) + revenue
        
        conf = get_casino_config(guild_id)
        conf["bank"] -= amount
        
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CASINO_CONFIG, conf)
        
        await interaction.response.send_message(f"💸 Ви обміняли `{amount}` фішок і отримали `{revenue} AC`.", ephemeral=True)

    @app_commands.command(name="chips", description="Переглянути свій баланс фішок казино")
    @app_commands.guild_only()
    async def chips_balance(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        uid = str(interaction.user.id)
        
        user_data = data.get(uid, {})
        chips = user_data.get("chips", 0)
        balance = user_data.get("balance", 0)
        
        embed = discord.Embed(
            title="Каса Казино",
            description="Ваші поточні рахунки:",
            color=0xf1c40f 
        )
        
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Фішки", value=f"🪙 `{chips}`", inline=True)
        embed.add_field(name="Готівка", value=f"💵 `{balance} AC`", inline=True)
        
        embed.set_footer(text="Увага: фішки автоматично конвертуються в AC через 30 хвилин бездіяльності.")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # === ІГРИ ===

    @app_commands.command(name="roulette", description="Грати в рулетку")
    @app_commands.guild_only()
    async def roulette(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Рулетка", 
            description="Зроби ставку, натиснувши кнопку або вибравши опцію нижче!\n\n*Курс: 1 фішка = 100 AC.*",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, view=RouletteView(self))

    @app_commands.command(name="slots", description="Ігрові автомати (3 в ряд)")
    @app_commands.guild_only()
    async def slots(self, interaction: discord.Interaction, bet: int):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        conf = get_casino_config(guild_id)
        uid = str(interaction.user.id)
        user = data.get(uid, {})

        if not process_bet(user, conf, bet):
            return await interaction.response.send_message("Некоректна ставка або недостатньо фішок (або перевищено ліміт).", ephemeral=True)

        conf["bank"] += bet
        save_guild_json(guild_id, DATA_FILE, data)
        
        await interaction.response.defer()

        emojis = ["🍒", "🍋", "🔔", "🍉", "⭐", "💎"]
        
        msg = await interaction.followup.send("`[ ? | ? | ? ]` Крутимо...", wait=True)
        await asyncio.sleep(1)
        await msg.edit(content=f"`[ {random.choice(emojis)} | ? | ? ]` Крутимо...")
        await asyncio.sleep(1)
        
        # === ПІДТАСОВКА КАЗИНО (RTP ~ 85%) ===
        roll = random.randint(1, 1000)
        
        if roll <= 600:
            res = random.sample(emojis, 3)
            mult = 0
        elif roll <= 800:
            a = random.choice(emojis)
            b = random.choice([e for e in emojis if e != a])
            res = [a, a, b]
            random.shuffle(res)
            mult = 0.5
        elif roll <= 930:
            a = random.choice(["🍒", "🍋", "🔔", "🍉"])
            res = [a, a, a]
            mult = 2
        elif roll <= 990:
            res = ["⭐", "⭐", "⭐"]
            mult = 5
        else:
            res = ["💎", "💎", "💎"]
            mult = 20

        if mult > 0 and (bet * mult) > conf["bank"]:
            res = random.sample(emojis, 3)
            mult = 0

        payout = int(bet * mult)
        
        final_str = f"🎰 `[ {res[0]} | {res[1]} | {res[2]} ]`\n\n"
        
        if payout > 0:
            user["chips"] += payout
            conf["bank"] -= payout
            embed = discord.Embed(title="JACKPOT!" if mult >= 5 else "ВИГРАШ!", description=final_str + f"Ви виграли `{payout}` фішок! (Множник: {mult}x)", color=0x2ecc71)
        else:
            embed = discord.Embed(title="ПРОГРАШ", description=final_str + f"Ваша ставка `{bet}` фішок згоріла.", color=0xe74c3c)

        embed.set_footer(text=f"Ваші фішки: {user['chips']}")
        
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CASINO_CONFIG, conf)
        
        await msg.edit(content=interaction.user.mention, embed=embed)

    @app_commands.command(name="dice", description="Зіграти в кості проти дилера")
    @app_commands.guild_only()
    async def dice(self, interaction: discord.Interaction, bet: int):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        conf = get_casino_config(guild_id)
        uid = str(interaction.user.id)
        user = data.get(uid, {})

        if not process_bet(user, conf, bet):
            return await interaction.response.send_message("Некоректна ставка або недостатньо фішок (або перевищено ліміт).", ephemeral=True)

        conf["bank"] += bet
        
        player_roll = random.randint(1, 6) + random.randint(1, 6)
        dealer_roll = random.randint(1, 6) + random.randint(1, 6)

        if random.random() < 0.15:
            dealer_roll = min(12, dealer_roll + 2)

        if player_roll > dealer_roll:
            payout = bet * 2
            user["chips"] += payout
            conf["bank"] -= payout
            color = 0x2ecc71
            title = "🎲 ВИГРАШ!"
            result_text = f"Ви виграли `{payout}` фішок!"
        else:
            color = 0xe74c3c
            title = "🎲 ПРОГРАШ"
            result_text = f"Ставка `{bet}` фішок згоріла. Нічия на користь казино!" if player_roll == dealer_roll else f"Ставка `{bet}` фішок згоріла."

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="Ваш кидок", value=f"**{player_roll}**", inline=True)
        embed.add_field(name="Кидок дилера", value=f"**{dealer_roll}**", inline=True)
        embed.description = result_text
        embed.set_footer(text=f"Ваші фішки: {user['chips']}")

        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CASINO_CONFIG, conf)

        await interaction.response.send_message(embed=embed)

    # === КОМАНДИ АДМІНІВ ===

    @app_commands.command(name="casino_set_maxbet", description="[АДМІН] Встановити максимальну ставку в казино (у фішках)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def set_maxbet(self, interaction: discord.Interaction, max_chips: int):
        guild_id = interaction.guild.id
        conf = get_casino_config(guild_id)
        conf["max_bet"] = max_chips
        save_guild_json(guild_id, CASINO_CONFIG, conf)
        await interaction.response.send_message(f"Максимальна ставка в казино тепер: `{max_chips}` фішок.", ephemeral=True)

    @app_commands.command(name="casino_fund", description="[АДМІН] Поповнити банк казино напряму")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def fund_casino(self, interaction: discord.Interaction, chips_amount: int):
        guild_id = interaction.guild.id
        conf = get_casino_config(guild_id)
        conf["bank"] += chips_amount
        save_guild_json(guild_id, CASINO_CONFIG, conf)
        await interaction.response.send_message(f"Банк казино поповнено на `{chips_amount}`. Поточний банк: `{conf['bank']}`.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(CasinoCog(bot))