import discord
from discord.ext import commands
from discord import app_commands
import os
from utils import load_guild_json, save_guild_json

ECONOMY_CONFIG = "economy_config.json"

class TaxesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_config(self, guild_id: int):
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        if not config:
            config = {"server_bank": 0}
        
        config.setdefault("bank_tax_rate", 0.01)
        config.setdefault("withdraw_fee", 0.01)
        config.setdefault("buy_commission", 0.05)
        config.setdefault("sell_commission", 0.05)
        config.setdefault("market_spread", 0.10)
        config.setdefault("paper_hands_tax", 0.15)
        
        return config

    @app_commands.command(name="taxes_info", description="Переглянути поточні податкові ставки на сервері")
    @app_commands.guild_only()
    async def taxes_info(self, interaction: discord.Interaction):
        config = self.get_config(interaction.guild.id)
        
        embed = discord.Embed(
            title="⚖️ Податкова Декларація Сервера", 
            description="Усі стягнення автоматично направляються до Державної Казни (СБ).",
            color=0x3498db
        )
        
        bank_tax = round(config["bank_tax_rate"] * 100, 2)
        withdraw_fee = round(config["withdraw_fee"] * 100, 2)
        buy_comm = round(config["buy_commission"] * 100, 2)
        sell_comm = round(config["sell_commission"] * 100, 2)
        spread = round(config["market_spread"] * 100, 2)
        paper_tax = round(config["paper_hands_tax"] * 100, 2)
        
        embed.add_field(name="🏦 Банківська система", value=f"Щоденний податок на депозит: `{bank_tax}%`\nКомісія за зняття готівки: `{withdraw_fee}%`", inline=False)
        embed.add_field(name="🪙 Криптовалютна біржа", value=f"Комісія купівлі: `{buy_comm}%`\nКомісія продажу: `{sell_comm}%`\nСпред ринку: `{spread}%`\nШтраф за швидкий продаж (до 2 год): `{paper_tax}%`", inline=False)
        
        embed.set_footer(text="Змінювати податки можуть лише Адміністратори.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="tax_set", description="[АДМІН] Встановити новий розмір податку чи комісії")
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(tax_type=[
        app_commands.Choice(name="🏦 Щоденний податок на депозит", value="bank_tax_rate"),
        app_commands.Choice(name="📤 Комісія за зняття з банку", value="withdraw_fee"),
        app_commands.Choice(name="📥 Комісія купівлі крипти", value="buy_commission"),
        app_commands.Choice(name="📤 Комісія продажу крипти", value="sell_commission"),
        app_commands.Choice(name="📉 Риночний спред крипти", value="market_spread"),
        app_commands.Choice(name="⏳ Штраф за швидкий продаж крипти", value="paper_hands_tax")
    ])
    @app_commands.describe(percentage="Введіть відсоток (наприклад: 5 або 2.5). Не пишіть знак %.")
    @app_commands.guild_only()
    async def tax_set(self, interaction: discord.Interaction, tax_type: app_commands.Choice[str], percentage: float):
        if percentage < 0 or percentage > 100:
            return await interaction.response.send_message("❌ Відсоток має бути в межах від 0 до 100!", ephemeral=True)
            
        guild_id = interaction.guild.id
        config = self.get_config(guild_id)
        
        new_rate = percentage / 100.0
        
        config[tax_type.value] = new_rate
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        
        await interaction.response.send_message(f"Податок **{tax_type.name}** успішно змінено на `{percentage}%`!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TaxesCog(bot))