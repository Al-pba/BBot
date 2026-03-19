import discord
from discord.ext import commands
from discord import app_commands
import os
import time
from datetime import timedelta
from utils import load_guild_json, save_guild_json

MOD_CONFIG = "mod_config.json"

class ModCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_config(self, guild_id: int):
        """Отримує або створює конфігурацію модерації для сервера"""
        config = load_guild_json(guild_id, MOD_CONFIG)
        if not config:
            config = {
                "log_channel_id": None,
                "warnings": {}
            }
            save_guild_json(guild_id, MOD_CONFIG, config)
        
        if "log_channel_id" not in config: config["log_channel_id"] = None
        if "warnings" not in config: config["warnings"] = {}
        return config

    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        """Відправляє ембед у встановлений канал логів (якщо він є)"""
        config = self.get_config(guild.id)
        channel_id = config.get("log_channel_id")
        
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass # Немає прав на відправку

    # ==========================================
    # НАЛАШТУВАННЯ ЛОГІВ
    # ==========================================

    @app_commands.command(name="set_log_channel", description="[ВЛАСНИК/АДМІН] Встановити канал для логів модерації")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def set_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild.id
        config = self.get_config(guild_id)
        config["log_channel_id"] = channel.id
        save_guild_json(guild_id, MOD_CONFIG, config)
        
        await interaction.response.send_message(f"Канал для логів успішно встановлено: {channel.mention}", ephemeral=True)
        
        embed = discord.Embed(title="⚙️ Система логування активована", description=f"Модератор {interaction.user.mention} налаштував цей канал для логів.", color=0x2ecc71)
        await self.send_log(interaction.guild, embed)

    # ==========================================
    # ІВЕНТИ ДЛЯ ЛОГІВ (АВТОМАТИЧНІ)
    # ==========================================

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        
        embed = discord.Embed(title="Повідомлення видалено", color=0xe74c3c)
        embed.add_field(name="Автор", value=message.author.mention, inline=True)
        embed.add_field(name="Канал", value=message.channel.mention, inline=True)
        if message.content:
            embed.add_field(name="Вміст", value=message.content[:1024], inline=False)
        embed.set_footer(text=f"ID: {message.id}")
        
        await self.send_log(message.guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content: return
        
        embed = discord.Embed(title="Повідомлення змінено", color=0xf1c40f, url=after.jump_url)
        embed.add_field(name="Автор", value=before.author.mention, inline=True)
        embed.add_field(name="Канал", value=before.channel.mention, inline=True)
        embed.add_field(name="Було", value=before.content[:1024] or "Пусто", inline=False)
        embed.add_field(name="Стало", value=after.content[:1024] or "Пусто", inline=False)
        
        await self.send_log(before.guild, embed)

    # ==========================================
    # КОМАНДИ МОДЕРАЦІЇ
    # ==========================================

    @app_commands.command(name="clear", description="[МОД] Очистити повідомлення в каналі")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 100:
            return await interaction.response.send_message("Вкажіть кількість від 1 до 100.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        
        await interaction.followup.send(f"Видалено {len(deleted)} повідомлень.", ephemeral=True)
        
        embed = discord.Embed(title="Очищення чату", color=0x3498db)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="Канал", value=interaction.channel.mention, inline=True)
        embed.add_field(name="Кількість", value=str(len(deleted)), inline=True)
        await self.send_log(interaction.guild, embed)

    @app_commands.command(name="mute", description="[МОД] Відправити користувача в тайм-аут (мут)")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.choices(duration=[
        app_commands.Choice(name="1 хвилина", value=1),
        app_commands.Choice(name="10 хвилин", value=10),
        app_commands.Choice(name="1 година", value=60),
        app_commands.Choice(name="1 доба", value=1440),
        app_commands.Choice(name="1 тиждень", value=10080)
    ])
    @app_commands.guild_only()
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: app_commands.Choice[int], reason: str = "Причина не вказана"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("Ви не можете замутити користувача, чия роль вища або дорівнює вашій.", ephemeral=True)
            
        time_duration = timedelta(minutes=duration.value)
        try:
            await member.timeout(time_duration, reason=reason)
            await interaction.response.send_message(f"🔇 Користувача {member.mention} відправлено в тайм-аут на {duration.name}. Причина: {reason}")
            
            embed = discord.Embed(title="🔇 Тайм-аут (Мут)", color=0xe67e22)
            embed.add_field(name="Користувач", value=member.mention, inline=True)
            embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
            embed.add_field(name="Тривалість", value=duration.name, inline=True)
            embed.add_field(name="Причина", value=reason, inline=False)
            await self.send_log(interaction.guild, embed)
        except Exception as e:
            await interaction.response.send_message(f"Не вдалося замутити: {e}", ephemeral=True)

    @app_commands.command(name="unmute", description="[МОД] Зняти тайм-аут з користувача")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        try:
            await member.timeout(None)
            await interaction.response.send_message(f"🔊 З користувача {member.mention} знято тайм-аут.")
            
            embed = discord.Embed(title="🔊 Зняття Тайм-ауту", color=0x2ecc71)
            embed.add_field(name="Користувач", value=member.mention, inline=True)
            embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
            await self.send_log(interaction.guild, embed)
        except Exception as e:
            await interaction.response.send_message(f"Помилка: {e}", ephemeral=True)

    @app_commands.command(name="kick", description="[АДМІН] Вигнати користувача з сервера")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Причина не вказана"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("Ви не можете вигнати цього користувача.", ephemeral=True)

        try:
            await member.send(f"Вас було вигнано з сервера **{interaction.guild.name}**. Причина: {reason}")
        except:
            pass 

        try:
            await member.kick(reason=reason)
            await interaction.response.send_message(f"Користувача {member.mention} вигнано. Причина: {reason}")
            
            embed = discord.Embed(title="Вигнання (Кік)", color=0xe74c3c)
            embed.add_field(name="Користувач", value=f"{member.name} ({member.id})", inline=True)
            embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
            embed.add_field(name="Причина", value=reason, inline=False)
            await self.send_log(interaction.guild, embed)
        except Exception as e:
            await interaction.response.send_message(f"Помилка: {e}", ephemeral=True)

    @app_commands.command(name="ban", description="[АДМІН] Заблокувати користувача")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Причина не вказана"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("Ви не можете забанити цього користувача.", ephemeral=True)

        try:
            await member.send(f"Вас було ЗАБАНЕНО на сервері **{interaction.guild.name}**. Причина: {reason}")
        except: pass

        try:
            await member.ban(reason=reason, delete_message_days=1)
            await interaction.response.send_message(f"🔨 Користувача {member.mention} заблоковано. Причина: {reason}")
            
            embed = discord.Embed(title="🔨 Блокування (Бан)", color=0x992d22)
            embed.add_field(name="Користувач", value=f"{member.name} ({member.id})", inline=True)
            embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
            embed.add_field(name="Причина", value=reason, inline=False)
            await self.send_log(interaction.guild, embed)
        except Exception as e:
            await interaction.response.send_message(f"Помилка: {e}", ephemeral=True)

    # ==========================================
    # СИСТЕМА ПОПЕРЕДЖЕНЬ (ВАРНІВ)
    # ==========================================

    @app_commands.command(name="warn", description="[МОД] Видати попередження (Варн)")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if member.bot: return await interaction.response.send_message("Не можна попередити бота.", ephemeral=True)
        
        guild_id = interaction.guild.id
        config = self.get_config(guild_id)
        uid = str(member.id)
        
        if uid not in config["warnings"]:
            config["warnings"][uid] = []
            
        warn_data = {
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": int(time.time())
        }
        
        config["warnings"][uid].append(warn_data)
        warn_count = len(config["warnings"][uid])
        save_guild_json(guild_id, MOD_CONFIG, config)
        
        await interaction.response.send_message(f"⚠️ Користувач {member.mention} отримав попередження (Всього: **{warn_count}**). Причина: {reason}")
        
        try:
            await member.send(f"⚠️ Ви отримали попередження на сервері **{interaction.guild.name}**.\nПричина: {reason}\nКількість попереджень: {warn_count}")
        except: pass

        embed = discord.Embed(title="⚠️ Попередження (Варн)", color=0xf1c40f)
        embed.add_field(name="Користувач", value=member.mention, inline=True)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="Варн №", value=str(warn_count), inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        await self.send_log(interaction.guild, embed)

    @app_commands.command(name="warnings", description="[МОД] Переглянути попередження користувача")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.User):
        config = self.get_config(interaction.guild.id)
        uid = str(member.id)
        
        warns = config["warnings"].get(uid, [])
        if not warns:
            return await interaction.response.send_message(f"У {member.display_name} немає попереджень.", ephemeral=True)
            
        embed = discord.Embed(title=f"Попередження: {member.display_name}", color=0xf1c40f)
        for i, w in enumerate(warns, 1):
            mod_mention = f"<@{w['moderator']}>"
            date = f"<t:{w['timestamp']}:d>"
            embed.add_field(name=f"Варн #{i} | {date}", value=f"**Видав:** {mod_mention}\n**Причина:** {w['reason']}", inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clear_warnings", description="[АДМІН] Очистити всі попередження користувача")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def clear_warnings(self, interaction: discord.Interaction, member: discord.User):
        guild_id = interaction.guild.id
        config = self.get_config(guild_id)
        uid = str(member.id)
        
        if uid in config["warnings"]:
            del config["warnings"][uid]
            save_guild_json(guild_id, MOD_CONFIG, config)
            await interaction.response.send_message(f"Всі попередження з {member.mention} було знято.", ephemeral=True)
            
            embed = discord.Embed(title="Амністія", description=f"Всі попередження користувача {member.mention} очищено модератором {interaction.user.mention}.", color=0x2ecc71)
            await self.send_log(interaction.guild, embed)
        else:
            await interaction.response.send_message("У цього користувача немає попереджень.", ephemeral=True)

    # ==========================================
    # УПРАВЛІННЯ КАНАЛАМИ
    # ==========================================

    @app_commands.command(name="lock", description="[МОД] Заблокувати поточний канал (заборонити писати)")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def lock(self, interaction: discord.Interaction):
        channel = interaction.channel
        default_role = interaction.guild.default_role
        
        overwrites = channel.overwrites_for(default_role)
        overwrites.send_messages = False
        await channel.set_permissions(default_role, overwrite=overwrites)
        
        embed = discord.Embed(title="🔒 Канал заблоковано", description="Спілкування тимчасово призупинено модератором.", color=0xe74c3c)
        await interaction.response.send_message(embed=embed)
        await self.send_log(interaction.guild, discord.Embed(title="🔒 Блокування каналу", description=f"Канал {channel.mention} заблоковано {interaction.user.mention}", color=0xe74c3c))

    @app_commands.command(name="unlock", description="[МОД] Розблокувати поточний канал")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def unlock(self, interaction: discord.Interaction):
        channel = interaction.channel
        default_role = interaction.guild.default_role
        
        overwrites = channel.overwrites_for(default_role)
        overwrites.send_messages = None
        await channel.set_permissions(default_role, overwrite=overwrites)
        
        embed = discord.Embed(title="🔓 Канал розблоковано", description="Ви знову можете писати повідомлення.", color=0x2ecc71)
        await interaction.response.send_message(embed=embed)
        await self.send_log(interaction.guild, discord.Embed(title="🔓 Розблокування каналу", description=f"Канал {channel.mention} розблоковано {interaction.user.mention}", color=0x2ecc71))

async def setup(bot):
    await bot.add_cog(ModCog(bot))