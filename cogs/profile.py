import discord
from discord.ext import commands
from discord import app_commands
import time
from collections import Counter
from utils import load_guild_json, save_guild_json

DATA_FILE = "users.json"
ITEMS_TEMPLATES = "items_templates.json"

# ==========================================
# БАЗОВИЙ КЛАС ДЛЯ UI (ОПТИМІЗАЦІЯ)
# ==========================================

class ProfileBaseView(discord.ui.View):
    """Базовий клас для перевірки, що кнопки тисне тільки автор команди."""
    def __init__(self, target_user: discord.User, cog: commands.Cog, author_id: int):
        super().__init__(timeout=180)
        self.target_user = target_user
        self.cog = cog
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("Це не ваше меню!", ephemeral=True)
        return False

# ==========================================
# ДОПОМІЖНІ СТОРІНКИ
# ==========================================

class StatsProfileView(ProfileBaseView):
    @discord.ui.button(label="Назад", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.cog.get_user_data(data, self.target_user.id)
        
        member = interaction.guild.get_member(self.target_user.id)
        embed = self.cog.build_main_embed(self.target_user, member, user_data)
        await interaction.response.edit_message(embed=embed, view=MainProfileView(self.target_user, self.cog, self.author_id))

class InventoryProfileView(ProfileBaseView):
    @discord.ui.button(label="Назад", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.cog.get_user_data(data, self.target_user.id)
        
        member = interaction.guild.get_member(self.target_user.id)
        embed = self.cog.build_main_embed(self.target_user, member, user_data)
        await interaction.response.edit_message(embed=embed, view=MainProfileView(self.target_user, self.cog, self.author_id))

# ==========================================
# ГОЛОВНЕ МЕНЮ
# ==========================================

class MainProfileView(discord.ui.View):
    def __init__(self, target_user: discord.User, cog: commands.Cog, author_id: int):
        super().__init__(timeout=180)
        self.target_user = target_user
        self.cog = cog
        self.author_id = author_id

    async def check_author(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("Це не ваше меню!", ephemeral=True)
        return False

    async def handle_vote(self, interaction: discord.Interaction, vote_type: str):
        if interaction.user.id == self.target_user.id:
            return await interaction.response.send_message("Ви не можете оцінювати себе.", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.cog.get_user_data(data, self.target_user.id)
        voter_id = str(interaction.user.id)
        
        current_vote = user_data.setdefault("voters", {}).get(voter_id)
        if current_vote == vote_type:
            return await interaction.response.send_message("⚠️ Ви вже так проголосували.", ephemeral=True)

        if current_vote == "like": user_data["likes"] -= 1
        elif current_vote == "dislike": user_data["dislikes"] -= 1

        if vote_type == "like": user_data["likes"] += 1
        else: user_data["dislikes"] += 1

        user_data["voters"][voter_id] = vote_type
        save_guild_json(guild_id, DATA_FILE, data)

        member = interaction.guild.get_member(self.target_user.id)
        new_embed = self.cog.build_main_embed(self.target_user, member, user_data)
        await interaction.response.edit_message(embed=new_embed, view=self)

    @discord.ui.button(label="Інвентар", style=discord.ButtonStyle.primary, row=0, emoji="🎒")
    async def inventory_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction): return 
        
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.cog.get_user_data(data, self.target_user.id)
        embed = self.cog.build_inventory_embed(self.target_user, user_data, guild_id)
        await interaction.response.edit_message(embed=embed, view=InventoryProfileView(self.target_user, self.cog, self.author_id))

    @discord.ui.button(label="Характеристики", style=discord.ButtonStyle.primary, row=0, emoji="📊")
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction): return 
        
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.cog.get_user_data(data, self.target_user.id)
        embed = self.cog.build_stats_embed(self.target_user, user_data)
        await interaction.response.edit_message(embed=embed, view=StatsProfileView(self.target_user, self.cog, self.author_id))

    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.success, row=0)
    async def like_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "like")

    @discord.ui.button(emoji="👎", style=discord.ButtonStyle.danger, row=0)
    async def dislike_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "dislike")

    @discord.ui.button(label="Крипто", style=discord.ButtonStyle.secondary, row=1)
    async def crypto_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction): return
        
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.cog.get_user_data(data, self.target_user.id)
        
        embed = discord.Embed(title=f"Крипто-гаманець: {self.target_user.name}", color=0xf2a900)
        crypto_data = user_data.get("crypto", {})
        desc = "\n".join([f"**{sym}**: `{amt:.4f}`" for sym, amt in crypto_data.items() if amt > 0])
        embed.description = desc if desc else "Гаманець порожній."
        
        await interaction.response.edit_message(embed=embed, view=InventoryProfileView(self.target_user, self.cog, self.author_id))

    # === НОВА КНОПКА: ПРИВАТНІСТЬ БАНКУ ===
    @discord.ui.button(label="Приватність банку", style=discord.ButtonStyle.secondary, row=1, emoji="👁️")
    async def privacy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction): return
        if interaction.user.id != self.target_user.id:
            return await interaction.response.send_message("❌ Ви можете змінювати приватність лише у власному профілі!", ephemeral=True)
            
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.cog.get_user_data(data, self.target_user.id)
        
        current_status = user_data.get("bank_hidden", False)
        user_data["bank_hidden"] = not current_status
        save_guild_json(guild_id, DATA_FILE, data)
        
        state = "приховано (***)" if user_data["bank_hidden"] else "відкрито"
        await interaction.response.send_message(f"🏦 Ваш банківський рахунок тепер {state} для інших.", ephemeral=True)


# ==========================================
# COG КЛАС
# ==========================================

class ProfileCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Автоматично запускає сканування повідомлень при додаванні бота на новий сервер"""
        
        target_channel = guild.system_channel
        if not target_channel or not target_channel.permissions_for(guild.me).send_messages:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    target_channel = channel
                    break
        
        if target_channel:
            await target_channel.send("👋 Привіт! Дякую за запрошення. \n🔄 Я автоматично розпочав фонове сканування історії повідомлень цього сервера, щоб налаштувати статистику гравців у профілях. Я повідомлю, коли закінчу!")

        self.bot.loop.create_task(self._background_sync(guild, target_channel))

    @commands.command(name="sync_msgs", description="[Власник] Глибоке сканування історії повідомлень")
    @commands.guild_only()
    async def sync_msgs(self, ctx):
        if ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("❌ Ця команда доступна лише власнику сервера.")

        await ctx.send("🔄 Починаю глибоке сканування всіх каналів. Це може зайняти від кількох хвилин до години. Я напишу, коли закінчу!")
        
        guild_id = ctx.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        
        user_counts = {}
        total_scanned = 0
        
        for channel in ctx.guild.text_channels:
            try:
                async for message in channel.history(limit=None):
                    if not message.author.bot: # Ботів не рахуємо
                        uid = str(message.author.id)
                        user_counts[uid] = user_counts.get(uid, 0) + 1
                    total_scanned += 1
            except discord.Forbidden:
                continue 
            except Exception as e:
                print(f"Помилка при читанні каналу {channel.name}: {e}")

        for uid, count in user_counts.items():
            if uid not in data:
                data[uid] = self.get_user_data(data, uid)
            data[uid]["messages"] = count 

        save_guild_json(guild_id, DATA_FILE, data)
        
        await ctx.send(f"✅ **Глибоке сканування завершено!**\nПроаналізовано повідомлень: `{total_scanned}`.\nБаза даних оновлена, тепер профілі показують всю історію від початку створення сервера!")

    async def _background_sync(self, guild: discord.Guild, notify_channel: discord.TextChannel = None):
        """Фонова функція для сканування історії"""
        data = load_guild_json(guild.id, DATA_FILE)
        user_counts = {}
        total_scanned = 0
        
        for channel in guild.text_channels:
            try:
                async for message in channel.history(limit=None):
                    if not message.author.bot:
                        uid = str(message.author.id)
                        user_counts[uid] = user_counts.get(uid, 0) + 1
                    total_scanned += 1
            except discord.Forbidden:
                continue 
            except Exception as e:
                print(f"Помилка сканування {channel.name}: {e}")

        for uid, count in user_counts.items():
            if uid not in data:
                data[uid] = self.get_user_data(data, uid)
            data[uid]["messages"] = count 

        save_guild_json(guild.id, DATA_FILE, data)
        
        if notify_channel:
            try:
                await notify_channel.send(f"✅ **Автоматичне налаштування завершено!**\nПроаналізовано повідомлень: `{total_scanned}`. База даних профілів повністю готова до роботи.")
            except:
                pass

    def get_user_data(self, data, user_id):
        uid = str(user_id)
        if uid not in data:
            data[uid] = {} 
        
        u = data[uid]
        u.setdefault("level", 1)
        u.setdefault("balance", 100)
        u.setdefault("likes", 0)
        u.setdefault("dislikes", 0)
        u.setdefault("mod_mark", "Нейтральна")
        u.setdefault("bank", 0)
        u.setdefault("bank_hidden", False) 
        u.setdefault("inventory", [])
        u.setdefault("crypto", {})
        u.setdefault("messages", 0)
        u.setdefault("last_seen", 0)
        u.setdefault("voters", {})

        if "property" in u:
            del u["property"]

        if "stats" not in u:
            u["stats"] = {"strength": 1, "agility": 1, "physique": 1, "intelligence": 1, "wisdom": 1, "charisma": 1}
        else:
            u["stats"].setdefault("physique", 1)

        return u

    def build_main_embed(self, user: discord.User, member: discord.User, user_data: dict) -> discord.Embed:
        last_seen = f"<t:{user_data['last_seen']}:R>" if user_data["last_seen"] > 0 else "Ніколи"
        
        embed = discord.Embed(title=f"👤 Профіль: {user.name}", color=0x2b2d31)
        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="Рівень / Баланс", value=f"Рівень: `{user_data['level']}`\nГотівка: `{user_data['balance']} AC`", inline=True)
        embed.add_field(name="Рейтинг", value=f"👍 `{user_data['likes']}` | 👎 `{user_data['dislikes']}`", inline=True)
        embed.add_field(name="Статус", value=f"**{user_data['mod_mark']}**", inline=True)

        if member:
            joined = f"<t:{int(member.joined_at.timestamp())}:D>"
            role = member.top_role.mention
            state = "🟢 На сервері"
        else:
            joined = "Невідомо (поза сервером)"
            role = "@everyone"
            state = "⚪ Офлайн-профіль"

        job_info = user_data.get("job", {})
        if job_info.get("company_id"):
            embed.add_field(name="Робота", value=f"Посада: `{job_info['profession'].capitalize()}`", inline=True)
        else:
            embed.add_field(name="Робота", value="Безробітний", inline=True)

        embed.add_field(name="📅 Приєднання", value=joined, inline=True)
        embed.add_field(name="Найвища роль", value=role, inline=True)
        embed.add_field(name="Стан", value=state, inline=True)
        
        embed.add_field(name="Активність", value=f"Повідомлень: `{user_data['messages']}`\nОстанній раз: {last_seen}", inline=False)
        embed.set_footer(text=f"ID: {user.id}")
        return embed

    def build_stats_embed(self, user: discord.User, user_data: dict) -> discord.Embed:
        embed = discord.Embed(title=f"Характеристики: {user.name}", color=0x3498db)
        s = user_data["stats"]
        desc = (f"⚔️ Сила: `{s['strength']}`\n🏃 Спритність: `{s['agility']}`\n❤️ Тілобудова: `{s['physique']}`\n"
                f"🧠 Інтелект: `{s['intelligence']}`\n📖 Мудрість: `{s['wisdom']}`\n🎭 Харизма: `{s['charisma']}`")
        embed.description = desc
        return embed

    def build_inventory_embed(self, user: discord.User, user_data: dict, guild_id: int) -> discord.Embed:
        embed = discord.Embed(title=f"🎒 Інвентар: {user.name}", color=0x2ecc71)
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        inv_counts = Counter(user_data.get("inventory", []))
        inv_list = []
        for i_id, count in inv_counts.items():
            item = templates.get(i_id, {"name": i_id, "rarity": "❓"})
            inv_list.append(f"{item.get('rarity', '')} {item.get('name')} x{count}")

        if user_data.get("bank_hidden", False):
            bank_display = "*** AC"
        else:
            bank_display = f"{user_data.get('bank', 0)} AC"

        embed.add_field(name="🏦 Банк", value=f"`{bank_display}`", inline=False)
        embed.add_field(name="🎒 Вміст рюкзака", value="\n".join(inv_list) if inv_list else "Порожньо", inline=True)
        
        return embed

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        guild_id = message.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user = self.get_user_data(data, message.author.id)
        user["messages"] += 1
        user["last_seen"] = int(time.time())
        save_guild_json(guild_id, DATA_FILE, data)

    @app_commands.command(name="profile", description="Переглянути профіль ")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, user: discord.User = None):
        target_user = user or interaction.user
        data = load_guild_json(interaction.guild.id, DATA_FILE)
        user_data = self.get_user_data(data, target_user.id)
        
        member = interaction.guild.get_member(target_user.id)
        
        embed = self.build_main_embed(target_user, member, user_data)
        view = MainProfileView(target_user, self, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="setmark", description="[Адмін] Встановити позначку користувачу")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.choices(mark=[
        app_commands.Choice(name="Позитивна", value="Позитивна"),
        app_commands.Choice(name="Нейтральна", value="Нейтральна"),
        app_commands.Choice(name="Агресивна", value="Агресивна")
    ])
    async def setmark(self, interaction: discord.Interaction, user: discord.User, mark: app_commands.Choice[str]):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.get_user_data(data, user.id)
        user_data["mod_mark"] = mark.value
        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"Позначку для **{user.name}** змінено на: **{mark.value}**.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ProfileCog(bot))