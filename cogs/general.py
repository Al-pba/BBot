import discord
from discord.ext import commands
from discord import app_commands
import platform
import os

DEVELOPER_IDS = [123456789012345678, 987654321098765432] 

def is_dev():
    """Кастомний декоратор, який замінює is_owner()"""
    def predicate(ctx):
        return ctx.author.id in DEVELOPER_IDS
    return commands.check(predicate)

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Перевірити затримку бота")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            description=f"⏳ Затримка сигналу: **{latency}мс**",
            color=0xB9FBC0 
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="server", description="Інформація про поточний сервер")
    @app_commands.guild_only()
    async def server(self, interaction: discord.Interaction):
        guild = interaction.guild
        
        embed = discord.Embed(title=f"Інформація про {guild.name}", color=0xCFBAF0)
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        
        created_at = int(guild.created_at.timestamp())
        
        embed.add_field(name="Власник", value=guild.owner.mention, inline=True)
        embed.add_field(name="Учасники", value=f"{guild.member_count}", inline=True)
        embed.add_field(name="Створено", value=f"<t:{created_at}:D>", inline=True)
        embed.add_field(name="Бусти", value=f"Рівень {guild.premium_tier} ({guild.premium_subscription_count} бустів)", inline=True)
        embed.add_field(name="ID Сервера", value=f"`{guild.id}`", inline=True)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="user", description="Отримати досьє на користувача")
    @app_commands.describe(member="Користувач, про якого хочете дізнатися")
    @app_commands.guild_only()
    async def user(self, interaction: discord.Interaction, member: discord.User = None):
        member = member or interaction.user
        
        embed = discord.Embed(title=f"Профіль: {member.display_name}", color=0xCAF0F8)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        roles = [role.mention for role in member.roles[1:]]
        roles_display = ", ".join(roles) if roles else "Немає"
        
        joined_at = int(member.joined_at.timestamp())
        created_at = int(member.created_at.timestamp())

        embed.add_field(name="Ім'я в мережі", value=member.name, inline=True)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Реєстрація", value=f"<t:{created_at}:R>", inline=True)
        embed.add_field(name="Приєднався", value=f"<t:{joined_at}:R>", inline=True)
        embed.add_field(name="Ролі", value=roles_display, inline=False)
        
        embed.set_footer(text=f"Запит від {interaction.user.name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botinfo", description="Технічна інформація про бота")
    async def botinfo(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Технічні характеристики бота", color=0xFFCFD2)
        
        embed.add_field(name="Бібліотека", value=f"discord.py v{discord.__version__}", inline=True)
        embed.add_field(name="Python", value=f"v{platform.python_version()}", inline=True)
        embed.add_field(name="ОС", value=platform.system(), inline=True)
        embed.add_field(name="Сервери", value=f"{len(self.bot.guilds)}", inline=True)
        embed.add_field(name="Користувачі", value=f"{sum(g.member_count for g in self.bot.guilds)}", inline=True)
        
        embed.set_footer(text="Розроблено для Woodland Rise")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Показати аватар користувача")
    @app_commands.describe(member="Чий аватар відкрити?")
    async def avatar(self, interaction: discord.Interaction, member: discord.User = None):
        member = member or interaction.user
        
        embed = discord.Embed(title=f"Аватар {member.display_name}", color=0xFDFD96)
        embed.set_image(url=member.display_avatar.url)
        
        embed.description = f"[Завантажити оригінал]({member.display_avatar.url})"
        await interaction.response.send_message(embed=embed)

    # ==========================================
    # АДМІНСЬКІ КОМАНДИ
    # ==========================================

    @commands.command(name="sync")
    @is_dev()
    async def sync(self, ctx):
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(f"✅ Успішно синхронізовано {len(synced)} слеш-команд!")
        except Exception as e:
            await ctx.send(f"❌ Помилка: {e}")

    @commands.command(name="reload", hidden=True)
    @is_dev()
    async def reload(self, ctx, extension: str):
        try:
            path = f"cogs.{extension}" if not extension.startswith("cogs.") else extension
            await self.bot.reload_extension(path)
            await ctx.send(f"✅ Модуль `{extension}` перезавантажено!")
        except Exception as e:
            await ctx.send(f"❌ Помилка: ```python\n{e}\n```")

    @commands.command(name="reloadall", hidden=True)
    @is_dev()
    async def reloadall(self, ctx):
        success_count = 0
        failed = []

        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                ext = f"cogs.{filename[:-3]}"
                try:
                    if ext in self.bot.extensions:
                        await self.bot.reload_extension(ext)
                    else:
                        await self.bot.load_extension(ext)
                    success_count += 1
                except Exception as e:
                    failed.append(f"`{ext}`: {e}")

        msg = f"✅ Успішно оновлено **{success_count}** модулів!"
        if failed:
            msg += "\n❌ **Помилки при завантаженні:**\n" + "\n".join(failed)
            
        await ctx.send(msg)

async def setup(bot):
    await bot.add_cog(General(bot))