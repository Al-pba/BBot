import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, time, random, math, uuid
from datetime import datetime
from datetime import time as dt_time, timezone, timedelta

from fontTools import diff
from utils import load_guild_json, save_guild_json

DATA_FILE = "users.json"
RPG_CONFIG = "rpg_config.json"
ECONOMY_CONFIG = "economy_config.json"
QUESTS_FILE = "quests.json"

STATS_UA = {
    "strength": "Сила",
    "agility": "Спритність",
    "physique": "Тілобудова",
    "intelligence": "Інтелект",
    "wisdom": "Мудрість",
    "charisma": "Харизма"
}

QUEST_TYPES_UA = {
    "messages": "Написати повідомлень",
    "voice": "Провести хвилин у войсі",
    "reactions": "Поставити реакцій",
    "commands": "Використати команд бота"
}

# ==========================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ==========================================

def get_upgrade_cost(current_level: int, is_main_level: bool = False) -> int:
    """
    Формула: (рівень)**2 * ln(рівень).
    Для загального рівня вартість множиться на 2.
    """
    if current_level <= 1:
        base_cost = 15
    else:
        base_cost = max(15, int((current_level ** 2) * math.log(current_level)))
        
    return base_cost * 2 if is_main_level else base_cost

def get_quests_data(guild_id: int) -> dict:
    data = load_guild_json(guild_id, QUESTS_FILE)
    if "active_quests" not in data:
        data["active_quests"] = {}
    return data

# ==========================================
# UI: ПРОКАЧКА
# ==========================================

class UpgradeSelect(discord.ui.Select):
    def __init__(self, cog, user_id: str, guild_id: int):
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id 
        
        data = load_guild_json(guild_id, DATA_FILE) 
        user = cog.get_user(data, user_id)
        stats = user["stats"]
        
        options = []
        for stat_key, stat_name in STATS_UA.items():
            lvl = stats.get(stat_key, 1)
            cost = get_upgrade_cost(lvl)
            options.append(discord.SelectOption(
                label=f"{stat_name} (Пот. рівень: {lvl})",
                value=stat_key,
                description=f"Ціна покращення: {cost} AC",
                emoji="📈"
            ))
            
        main_lvl = user.get("level", 1)
        main_cost = get_upgrade_cost(main_lvl, is_main_level=True) 
        options.append(discord.SelectOption(
            label=f"🌟 Загальний рівень (Пот: {main_lvl})",
            value="main_level",
            description=f"Ціна покращення: {main_cost} AC"
        ))
        
        super().__init__(placeholder="Оберіть характеристику для прокачки...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ Це не ваше меню!", ephemeral=True)
            
        stat_key = self.values[0]
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user = self.cog.get_user(data, self.user_id)
        
        if stat_key == "main_level":
            current_lvl = user.get("level", 1)
            cost = get_upgrade_cost(current_lvl, is_main_level=True) 
            if user["balance"] < cost:
                return await interaction.response.send_message(f"❌ Недостатньо коштів. Потрібно: `{cost} AC`.", ephemeral=True)
                
            user["balance"] -= cost
            user["level"] = current_lvl + 1
            msg = f"🌟 Ваш загальний рівень підвищено до **{user['level']}**!"
        else:
            current_lvl = user["stats"].get(stat_key, 1)
            cost = get_upgrade_cost(current_lvl) 
            if user["balance"] < cost:
                return await interaction.response.send_message(f"❌ Недостатньо коштів. Потрібно: `{cost} AC`.", ephemeral=True)
                
            user["balance"] -= cost
            new_lvl = current_lvl + 1
            user["stats"][stat_key] = new_lvl
            
            msg = f"📈 Характеристика **{STATS_UA[stat_key]}** підвищена до **{new_lvl}**!"
            
            if new_lvl % 10 == 0:
                user["level"] = user.get("level", 1) + 1
                msg += f"\n🎉 За досягнення {new_lvl} рівня у цій навичці, ваш загальний рівень автоматично зріс до **{user['level']}**!"

        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.edit_message(content=msg, view=UpgradeView(self.cog, self.user_id, guild_id))

class UpgradeView(discord.ui.View):
    def __init__(self, cog, user_id: str, guild_id: int):
        super().__init__(timeout=120)
        self.add_item(UpgradeSelect(cog, user_id, guild_id))

# ==========================================
# UI: ЩОДЕННИЙ КВЕСТ ТА ПОКАРАННЯ
# ==========================================

class DailyView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Отримати Дейлік", style=discord.ButtonStyle.success, emoji="🎁", custom_id="daily_quest_btn")
    async def daily_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_id = str(interaction.user.id)
        user = self.cog.get_user(data, user_id)
        
        today = time.strftime("%Y-%m-%d")
        if user.get("last_daily_date") == today:
            return await interaction.response.send_message("❌ Ви вже отримали нагороду сьогодні! Приходьте завтра.", ephemeral=True)
            
        user["balance"] += 100
        user["last_daily_date"] = today
        
        random_stat = random.choice(list(STATS_UA.keys()))
        user["stats"][random_stat] = user["stats"].get(random_stat, 1) + 1
        
        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"🎁 **Виконано!** Ви отримали `100 AC` та +1 до **{STATS_UA[random_stat]}**!", ephemeral=True)

class PunishView(discord.ui.View):
    def __init__(self, thief: discord.User, victim: discord.User, cog):
        super().__init__(timeout=600) 
        self.thief = thief
        self.victim = victim
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.victim.id:
            await interaction.response.send_message("❌ Тільки жертва крадіжки може обрати покарання!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content=f"⏳ Час на покарання вийшов. Крадій зміг вирватися і втекти!", view=self)
        except:
            pass

    @discord.ui.button(label="Зв'язати", style=discord.ButtonStyle.danger, emoji="⛓️")
    async def btn_tie(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        thief_data = self.cog.get_user(data, str(self.thief.id))
        
        thief_data["caught_until"] = 0 
        thief_data["tied_up_until"] = int(time.time()) + 7200
        save_guild_json(guild_id, DATA_FILE, data)
        
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"⛓️ Ви зв'язали {self.thief.mention}. Він не зможе використовувати команди бота наступні 2 години!", view=self)

    @discord.ui.button(label="Відшкодування (-20%)", style=discord.ButtonStyle.primary, emoji="💸")
    async def btn_comp(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        thief_data = self.cog.get_user(data, str(self.thief.id))
        victim_data = self.cog.get_user(data, str(self.victim.id))
        
        fine = int(thief_data["balance"] * 0.20)
        thief_data["balance"] -= fine
        victim_data["balance"] += fine
        thief_data["caught_until"] = 0 
        
        save_guild_json(guild_id, DATA_FILE, data)
        
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"💸 Ви примусили {self.thief.mention} виплатити компенсацію у розмірі `{fine} AC`!", view=self)

    @discord.ui.button(label="Відпустити", style=discord.ButtonStyle.secondary, emoji="🕊️")
    async def btn_free(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        thief_data = self.cog.get_user(data, str(self.thief.id))
        
        thief_data["caught_until"] = 0 
        save_guild_json(guild_id, DATA_FILE, data)
        
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"🕊️ Ви проявили милосердя і відпустили {self.thief.mention}.", view=self)

# ==========================================
# ОСНОВНИЙ КОГ
# ==========================================

class RPGCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_quest_loop.start()
        self.quest_cleanup_loop.start()
        self.voice_tracker_loop.start()
        
        self.voice_sessions = {}
        
        self._original_interaction_check = bot.tree.interaction_check
        bot.tree.interaction_check = self.global_tie_check

    async def cog_unload(self):
        self.bot.tree.interaction_check = self._original_interaction_check
        self.daily_quest_loop.cancel()
        self.quest_cleanup_loop.cancel()
        self.voice_tracker_loop.cancel()

    async def global_tie_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild:
            data = load_guild_json(interaction.guild.id, DATA_FILE)
            user_data = data.get(str(interaction.user.id), {})
            tied_until = user_data.get("tied_up_until", 0)
            
            if tied_until > int(time.time()):
                await interaction.response.send_message(f"⛓️ Ви міцно зв'язані! Ви не можете взаємодіяти з ботом ще <t:{tied_until}:R>.", ephemeral=True)
                return False
                
        if self._original_interaction_check:
            return await self._original_interaction_check(interaction)
        return True

    def get_user(self, data, uid):
        uid = str(uid)
        if uid not in data: data[uid] = {}
        data[uid].setdefault("balance", 0)
        data[uid].setdefault("level", 1)
        data[uid].setdefault("stats", {"strength": 1, "agility": 1, "physique": 1, "intelligence": 1, "wisdom": 1, "charisma": 1})
        data[uid].setdefault("last_daily_date", "")
        data[uid].setdefault("tied_up_until", 0)
        data[uid].setdefault("steal_cooldown", 0)
        data[uid].setdefault("caught_until", 0) 
        return data[uid]

    # --- СИСТЕМА КВЕСТІВ (ФОНОВІ ЗАВДАННЯ) ---

    async def update_quest_progress(self, guild_id: int, user_id: int, q_type: str, amount: int = 1):
        """Оновлює прогрес квесту для гравця і видає нагороду, якщо виконано."""
        q_data = get_quests_data(guild_id)
        u_data = load_guild_json(guild_id, DATA_FILE)
        uid_str = str(user_id)
        
        updated = False
        current_time = int(time.time())
        
        for q_id, quest in list(q_data["active_quests"].items()):
            if current_time > quest["expires_at"]: continue
            if quest["type"] != q_type: continue
            
            if "progress" not in quest: quest["progress"] = {}
            if "completed_by" not in quest: quest["completed_by"] = []
            
            if uid_str in quest["completed_by"] and not quest["repeatable"]:
                continue
                
            current = quest["progress"].get(uid_str, 0)
            new_progress = current + amount
            quest["progress"][uid_str] = new_progress
            updated = True
            
            if new_progress >= quest["target"]:
                user = self.get_user(u_data, uid_str)
                user["balance"] += quest["reward"]
                
                quest["completed_by"].append(uid_str)
                quest["progress"][uid_str] = 0 
                
                guild = self.bot.get_guild(guild_id)
                if guild:
                    member = guild.get_member(user_id)
                    if member:
                        try:
                            await member.send(f"🎉 **Квест виконано!** Ви успішно {QUEST_TYPES_UA[q_type].lower()} `{quest['target']}` разів!\nВаша нагорода: `{quest['reward']} AC` 💰")
                        except: pass
                
        if updated:
            save_guild_json(guild_id, QUESTS_FILE, q_data)
            save_guild_json(guild_id, DATA_FILE, u_data)

    @tasks.loop(minutes=5)
    async def quest_cleanup_loop(self):
        """Видаляє прострочені квести"""
        if not os.path.exists("server_data"): return
        current_time = int(time.time())
        
        for gid_str in os.listdir("server_data"):
            try:
                guild_id = int(gid_str)
                q_data = get_quests_data(guild_id)
                expired = [qid for qid, q in q_data["active_quests"].items() if current_time > q["expires_at"]]
                
                if expired:
                    for qid in expired: del q_data["active_quests"][qid]
                    save_guild_json(guild_id, QUESTS_FILE, q_data)
            except: pass

    @quest_cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # --- ВІДСТЕЖЕННЯ ПОДІЙ ДЛЯ КВЕСТІВ ---

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        await self.update_quest_progress(message.guild.id, message.author.id, "messages", 1)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.member and not payload.member.bot:
            await self.update_quest_progress(payload.guild_id, payload.user_id, "reactions", 1)

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        if interaction.guild and not interaction.user.bot:
            await self.update_quest_progress(interaction.guild.id, interaction.user.id, "commands", 1)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
        guild_id = member.guild.id
        
        if guild_id not in self.voice_sessions:
            self.voice_sessions[guild_id] = {}
            
        if before.channel is None and after.channel is not None:
            self.voice_sessions[guild_id][member.id] = time.time()
            
        elif before.channel is not None and after.channel is None:
            start_time = self.voice_sessions[guild_id].pop(member.id, None)
            if start_time:
                minutes_spent = int((time.time() - start_time) / 60)
                if minutes_spent > 0:
                    await self.update_quest_progress(guild_id, member.id, "voice", minutes_spent)

    @tasks.loop(minutes=1)
    async def voice_tracker_loop(self):
        """Періодично оновлює прогрес для тих, хто довго сидить у войсі без виходу"""
        current_time = time.time()
        for guild_id, sessions in list(self.voice_sessions.items()):
            for user_id, start_time in list(sessions.items()):
                minutes_spent = int((current_time - start_time) / 60)
                if minutes_spent > 0:
                    await self.update_quest_progress(guild_id, user_id, "voice", minutes_spent)
                    self.voice_sessions[guild_id][user_id] = current_time

    @voice_tracker_loop.before_loop
    async def before_voice_tracker(self):
        await self.bot.wait_until_ready()

    # --- ЗАЛИШОК СТАРОГО КОДУ ---

    @tasks.loop(minutes=1)
    async def daily_quest_loop(self):
        """Перевіряє кожну хвилину, чи не настав час для дейліка на якомусь із серверів"""
        if not os.path.exists("server_data"): return
        
        now = datetime.now()
        current_time_str = now.strftime("%H:%M")
        today_str = now.strftime("%Y-%m-%d")
        
        for guild_id_str in os.listdir("server_data"):
            try:
                guild_id = int(guild_id_str)
                guild = self.bot.get_guild(guild_id)
                if not guild: continue
                
                config = load_guild_json(guild_id, RPG_CONFIG)
                channel_id = config.get("daily_channel_id")
                
                daily_time = config.get("daily_time", "18:00")
                last_sent = config.get("last_daily_sent_date", "")
                
                if channel_id and current_time_str == daily_time and last_sent != today_str:
                    channel = guild.get_channel(channel_id)
                    if channel:
                        embed = discord.Embed(
                            title="🌟 Щоденний Квест Доступний!", 
                            description=f"Натисніть кнопку нижче, щоб отримати свої 100 AC та +1 до випадкової характеристики!\n*Час щоденного оновлення: {daily_time}.*",
                            color=0xf1c40f
                        )
                        await channel.send(embed=embed, view=DailyView(self))
                        
                        config["last_daily_sent_date"] = today_str
                        save_guild_json(guild_id, RPG_CONFIG, config)
            except Exception as e:
                print(f"Помилка відправки дейліка для {guild_id_str}: {e}")

    @daily_quest_loop.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()

    # --- КОМАНДИ ---

    @app_commands.command(name="upgrade", description="Прокачати свої характеристики за AC")
    @app_commands.guild_only()
    async def upgrade_stats(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Оберіть, що бажаєте покращити:", 
            view=UpgradeView(self, str(interaction.user.id), interaction.guild.id), 
            ephemeral=True
        )

    @app_commands.command(name="steal", description="Спробувати обікрасти іншого гравця")
    @app_commands.guild_only()
    async def steal(self, interaction: discord.Interaction, victim: discord.User):
        if victim.id == interaction.user.id: return await interaction.response.send_message("Ви не можете обікрасти самого себе.", ephemeral=True)
        if victim.bot: return await interaction.response.send_message("У ботів немає кишень.", ephemeral=True)
            
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        
        thief_data = self.get_user(data, str(interaction.user.id))
        victim_data = self.get_user(data, str(victim.id))
        
        if thief_data.get("caught_until", 0) > int(time.time()):
            return await interaction.response.send_message("Ви спіймані на гарячому! Ви не можете красти, поки жертва не вирішить вашу долю.", ephemeral=True)
        
        if thief_data.get("steal_cooldown", 0) > int(time.time()):
            return await interaction.response.send_message(f"⏳ Заляжте на дно. Ви зможете красти знову <t:{thief_data['steal_cooldown']}:R>.", ephemeral=True)
            
        if victim_data["balance"] < 100:
            return await interaction.response.send_message("У цієї цілі занадто мало грошей у гаманці. Це того не варте.", ephemeral=True)

        thief_agi = thief_data["stats"].get("agility", 1)
        victim_wis = victim_data["stats"].get("wisdom", 1)
        
        diff = thief_agi - victim_wis
        chance = 50 + (diff * 1.5)
        chance = max(25, min(85, chance))
        
        thief_data["steal_cooldown"] = int(time.time()) + 3600 
        
        roll = random.randint(1, 100)
        
        if roll <= chance:
            percent = random.uniform(0.01, 0.05)
            stolen_amount = int(victim_data["balance"] * percent)
            
            victim_data["balance"] -= stolen_amount
            thief_data["balance"] += stolen_amount
            save_guild_json(guild_id, DATA_FILE, data)
            
            await interaction.response.send_message(f"🥷 **Успішна крадіжка!** Ви непомітно витягли `{stolen_amount} AC` з кишені {victim.display_name}.", ephemeral=True)
        else:
            thief_data["caught_until"] = int(time.time()) + 600
            save_guild_json(guild_id, DATA_FILE, data) 
            
            view = PunishView(interaction.user, victim, self)
            msg = await interaction.channel.send(
                content=f"🚨 Увага! {victim.mention}, гравець {interaction.user.mention} намагався обікрасти вас, але ви зловили його за руку!\n"
                        f"Ви маєте 10 хвилин, щоб обрати для нього покарання:",
                view=view
            )
            view.message = msg 
            
            await interaction.response.send_message("🚨 **ПРОВАЛ!** Вас спіймали на гарячому! Готуйтеся до наслідків...", ephemeral=True)

    @app_commands.command(name="bail", description="Внести заставу за зв'язаного гравця (1000 AC)")
    @app_commands.guild_only()
    async def bail(self, interaction: discord.Interaction, member: discord.User):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        
        target_data = self.get_user(data, str(member.id))
        payer_data = self.get_user(data, str(interaction.user.id))
        
        if target_data.get("tied_up_until", 0) <= int(time.time()):
            return await interaction.response.send_message(f"❌ {member.display_name} зараз не зв'язаний. Застава не потрібна.", ephemeral=True)
            
        bail_cost = 1000
        
        if payer_data["balance"] < bail_cost:
            return await interaction.response.send_message(f"❌ У вас недостатньо коштів! Застава коштує `{bail_cost} AC`.", ephemeral=True)
            
        payer_data["balance"] -= bail_cost
        config["server_bank"] = config.get("server_bank", 0) + bail_cost
        target_data["tied_up_until"] = 0
        
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        
        await interaction.response.send_message(f"⚖️ {interaction.user.mention} вніс заставу у розмірі `{bail_cost} AC`! Гравець {member.mention} знову на волі і може використовувати команди.")

    @app_commands.command(name="admin_quest_create", description="[АДМІН] Створити новий квест для гравців")
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(q_type=[
        app_commands.Choice(name="Написати повідомлення", value="messages"),
        app_commands.Choice(name="Хвилин у войсі", value="voice"),
        app_commands.Choice(name="Поставити реакції", value="reactions"),
        app_commands.Choice(name="Використати команди", value="commands")
    ])
    @app_commands.guild_only()
    async def admin_quest_create(self, interaction: discord.Interaction, name: str, q_type: app_commands.Choice[str], target: int, reward: int, repeatable: bool, expires_in_mins: int):
        guild_id = interaction.guild.id
        q_data = get_quests_data(guild_id)
        
        quest_id = str(uuid.uuid4())[:8]
        q_data["active_quests"][quest_id] = {
            "name": name,
            "type": q_type.value,
            "target": target,
            "reward": reward,
            "repeatable": repeatable,
            "expires_at": int(time.time()) + (expires_in_mins * 60),
            "progress": {},
            "completed_by": []
        }
        
        save_guild_json(guild_id, QUESTS_FILE, q_data)
        
        rep_text = "Так" if repeatable else "Ні"
        await interaction.response.send_message(
            f"✅ **Квест '{name}' успішно створено!** (ID: `{quest_id}`)\n"
            f"**Завдання:** {QUEST_TYPES_UA[q_type.value]} (`{target}` разів)\n"
            f"**Нагорода:** `{reward} AC`\n"
            f"**Перепроходження:** {rep_text}\n"
            f"**Зникне:** <t:{q_data['active_quests'][quest_id]['expires_at']}:R>",
            ephemeral=False
        )

    @app_commands.command(name="admin_quest_delete", description="[АДМІН] Видалити квест за ID")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def admin_quest_delete(self, interaction: discord.Interaction, quest_id: str):
        guild_id = interaction.guild.id
        q_data = get_quests_data(guild_id)
        
        if quest_id not in q_data["active_quests"]:
            return await interaction.response.send_message(f"❌ Квест з ID `{quest_id}` не знайдено.", ephemeral=True)
            
        del q_data["active_quests"][quest_id]
        save_guild_json(guild_id, QUESTS_FILE, q_data)
        await interaction.response.send_message(f"✅ Квест `{quest_id}` успішно видалено.", ephemeral=True)

    @app_commands.command(name="quests", description="Переглянути список доступних квестів та свій прогрес")
    @app_commands.guild_only()
    async def quests(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        q_data = get_quests_data(guild_id)
        uid_str = str(interaction.user.id)
        current_time = int(time.time())
        
        active = {k: v for k, v in q_data["active_quests"].items() if current_time <= v["expires_at"]}
        
        if not active:
            return await interaction.response.send_message("📭 Наразі немає активних квестів. Слідкуйте за оновленнями!", ephemeral=True)
            
        embed = discord.Embed(title="📜 Дошка Квестів", color=0x3498db)
        
        for q_id, q in active.items():
            completed = uid_str in q.get("completed_by", [])
            
            if completed and not q["repeatable"]:
                status = "✅ ВИКОНАНО"
                progress_text = f"Отримано нагороду: `{q['reward']} AC`"
            else:
                progress = q.get("progress", {}).get(uid_str, 0)
                status = "🔄 АКТИВНО" if not completed else "🔄 АКТИВНО (Повторно)"
                progress_text = f"Прогрес: `{progress}/{q['target']}`\nНагорода: `{q['reward']} AC`"
                
            rep_text = " | 🔁 Багаторазовий" if q["repeatable"] else ""
            desc = f"**Завдання:** {QUEST_TYPES_UA[q['type']]} {q['target']} разів.\n{progress_text}\n⏳ Завершується: <t:{q['expires_at']}:R>{rep_text}"
            
            embed.add_field(
                name=f"{status} | {q['name']} (ID: `{q_id}`)",
                value=desc,
                inline=False
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="set_daily_channel", description="[АДМІН] Встановити канал для щоденних квестів о 18:00")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def set_daily_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild.id
        config = load_guild_json(guild_id, RPG_CONFIG)
        config["daily_channel_id"] = channel.id
        save_guild_json(guild_id, RPG_CONFIG, config)
        await interaction.response.send_message(f"Тепер дейліки будуть з'являтися у каналі {channel.mention} щодня о 18:00.")

    @app_commands.command(name="set_daily_time", description="[АДМІН] Встановити час появи щоденного квесту")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        hour="Година (від 0 до 23)", 
        minute="Хвилина (від 0 до 59)"
    )
    @app_commands.guild_only()
    async def set_daily_time(self, interaction: discord.Interaction, hour: app_commands.Range[int, 0, 23], minute: app_commands.Range[int, 0, 59]):
        guild_id = interaction.guild.id
        config = load_guild_json(guild_id, RPG_CONFIG)
        
        time_str = f"{hour:02d}:{minute:02d}"
        config["daily_time"] = time_str
        save_guild_json(guild_id, RPG_CONFIG, config)
        
        await interaction.response.send_message(f"⏰ Час появи щоденного квесту успішно змінено на **{time_str}** (за часом сервера).", ephemeral=True)

    @app_commands.command(name="admin_give_stat", description="[АДМІН] Додати характеристику гравцю")
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(stat=[
        app_commands.Choice(name="Сила", value="strength"),
        app_commands.Choice(name="Спритність", value="agility"),
        app_commands.Choice(name="Тілобудова", value="physique"),
        app_commands.Choice(name="Інтелект", value="intelligence"),
        app_commands.Choice(name="Мудрість", value="wisdom"),
        app_commands.Choice(name="Харизма", value="charisma"),
        app_commands.Choice(name="Загальний рівень", value="level")
    ])
    @app_commands.guild_only()
    async def admin_give_stat(self, interaction: discord.Interaction, member: discord.User, stat: app_commands.Choice[str], amount: int):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.get_user(data, str(member.id))
        
        if stat.value == "level":
            user_data["level"] = max(1, user_data.get("level", 1) + amount)
            stat_name = "Загальний рівень"
            new_val = user_data["level"]
        else:
            user_data["stats"][stat.value] = max(1, user_data["stats"].get(stat.value, 1) + amount)
            stat_name = STATS_UA.get(stat.value, stat.value)
            new_val = user_data["stats"][stat.value]
            
        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"Адміністратор видав `+{amount}` до **{stat_name}** для {member.mention}. Тепер рівень: **{new_val}**.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RPGCog(bot))