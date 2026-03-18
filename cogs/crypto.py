import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, time, random, logging
import io
import asyncio
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, time as dt_time, timezone
from utils import load_guild_json, save_guild_json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CryptoBot")

SAVE_TIMES = [dt_time(hour=h, minute=0, tzinfo=timezone.utc) for h in range(0, 24, 2)]
DATA_FILE = "users.json"
ECONOMY_CONFIG = "economy_config.json"
CRYPTO_MARKET_FILE = "crypto_market.json"

# ==========================================
# ДОПОМІЖНА ФУНКЦІЯ: МАЛЮВАННЯ ГРАФІКА
# ==========================================

def generate_crypto_chart(market_data: dict) -> io.BytesIO:
    """Генерує графік криптовалют і повертає його як байтовий буфер (картинку)"""
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 5))
    
    has_data = False
    current_time = int(time.time())
    
    for symbol, info in market_data.items():
        history = list(info.get("history", []))
        
        if not history or history[-1]["time"] < current_time - 60:
            history.append({"time": current_time, "price": info["price"]})
            
        if len(history) == 1:
            history = [
                {"time": history[0]["time"] - 60, "price": history[0]["price"]},
                history[0]
            ]
            
        times = [datetime.fromtimestamp(pt["time"]) for pt in history]
        prices = [pt["price"] for pt in history]
        
        ax.plot(times, prices, marker='o', markersize=4, linestyle='-', linewidth=2, label=f"{info['name']} ({symbol})")
        has_data = True
        
    if not has_data:
        ax.text(0.5, 0.5, 'Немає даних для відображення', ha='center', va='center', transform=ax.transAxes)
        
    ax.set_title('Курс криптовалют (Останні 7 днів)', fontsize=14, pad=15)
    ax.set_ylabel('Ціна (AC)', fontsize=12)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
    plt.xticks(rotation=45) 
    
    ax.grid(True, alpha=0.2, linestyle='--')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.25), ncol=3, frameon=False)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig) 
    buf.seek(0)
    
    return buf

# ==========================================
# UI ДЛЯ КРИПТОБІРЖІ (МОДАЛЬНІ ВІКНА)
# ==========================================
class CryptoActionModal(discord.ui.Modal):
    def __init__(self, action: str, symbol: str, cog: commands.Cog):
        title = f"Купівля {symbol}" if action == "buy" else f"Продаж {symbol}"
        super().__init__(title=title)
        self.action = action
        self.symbol = symbol
        self.cog = cog
        
        self.amount_input = discord.ui.TextInput(
            label="Введіть потрібну кількість",
            style=discord.TextStyle.short,
            placeholder="Наприклад: 1 або 0.5",
            required=True
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        val_str = self.amount_input.value.replace(',', '.')
        
        try:
            amount = float(val_str)
        except ValueError:
            return await interaction.response.send_message("❌ Будь ласка, введіть коректне число!", ephemeral=True)
            
        if amount <= 0:
            return await interaction.response.send_message("❌ Кількість має бути більшою за 0!", ephemeral=True)

        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        data = load_guild_json(guild_id, DATA_FILE)
        
        uid = str(interaction.user.id)
        if uid not in data:
            data[uid] = {"balance": 0, "crypto": {}}
        user = data[uid]

        if self.symbol not in market:
            return await interaction.response.send_message("❌ Валюту не знайдено на біржі.", ephemeral=True)

        price = market[self.symbol]["price"]
        owner_id = str(market[self.symbol].get("owner"))

        if self.action == "buy":
            buy_commission = config.get("buy_commission", 0.05)
            total_cost = int(price * amount * (1 + buy_commission))
            
            if user.get("balance", 0) < total_cost:
                return await interaction.response.send_message(f"❌ Недостатньо AC! Треба `{total_cost}`.", ephemeral=True)

            commission_amount = int(price * amount * buy_commission)
            owner_share = int(price * amount * 0.01) if owner_id != "None" and owner_id != "None" else 0
            bank_share = commission_amount - owner_share

            user["balance"] -= total_cost
            config["server_bank"] = config.get("server_bank", 0) + bank_share
            
            if owner_id != "None" and owner_id in data:
                data[owner_id]["balance"] = data[owner_id].get("balance", 0) + owner_share
            
            user.setdefault("crypto", {})[self.symbol] = user["crypto"].get(self.symbol, 0) + amount
            user.setdefault("crypto_timestamps", {})[self.symbol] = int(time.time())

            msg = f"✅ Куплено **{amount} {self.symbol}** за `{total_cost} AC`."

        else:
            if self.symbol not in user.get("crypto", {}) or user["crypto"][self.symbol] < amount:
                return await interaction.response.send_message("❌ Недостатньо криптовалюти для продажу.", ephemeral=True)

            sell_commission = config.get("sell_commission", 0.05)
            market_spread = config.get("market_spread", 0.10)
            base_sell = int(price * amount * (1 - sell_commission - market_spread))
            
            owner_share = int(price * amount * 0.01) if owner_id != "None" else 0
            
            last_buy = user.get("crypto_timestamps", {}).get(self.symbol, 0)
            penalty_msg = ""
            if (int(time.time()) - last_buy) < 7200:
                penalty = int(base_sell * config.get("paper_hands_tax", 0.15))
                base_sell -= penalty
                config["server_bank"] = config.get("server_bank", 0) + penalty
                penalty_msg = f"\n⚠️ Штраф за швидкий продаж: -`{penalty} AC`"

            user["crypto"][self.symbol] -= amount
            user["balance"] += base_sell
            
            if owner_id != "None" and owner_id in data:
                data[owner_id]["balance"] = data[owner_id].get("balance", 0) + owner_share

            msg = f"✅ Продано **{amount} {self.symbol}** за `{base_sell} AC`.{penalty_msg}"

        market = self.cog.apply_market_impact(market, self.symbol, amount, is_buy=(self.action == "buy"))

        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
        
        await interaction.response.send_message(msg, ephemeral=True)

class CryptoSelect(discord.ui.Select):
    def __init__(self, market_data):
        options = []
        for sym, info in list(market_data.items())[:25]:
            options.append(discord.SelectOption(
                label=f"{info['name']} ({sym})",
                value=sym,
                description=f"Курс: {info['price']} AC",
                emoji="🪙"
            ))
        super().__init__(placeholder="Оберіть валюту для торгівлі...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_symbol = self.values[0]
        self.view.buy_btn.disabled = False
        self.view.sell_btn.disabled = False
        await interaction.response.edit_message(view=self.view)

class CryptoMarketView(discord.ui.View):
    def __init__(self, cog: commands.Cog, market_data: dict):
        super().__init__(timeout=None)
        self.cog = cog
        self.selected_symbol = None
        self.add_item(CryptoSelect(market_data))

    @discord.ui.button(label="Купити", style=discord.ButtonStyle.success, emoji="📥", disabled=True, row=1)
    async def buy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CryptoActionModal("buy", self.selected_symbol, self.cog))

    @discord.ui.button(label="Продати", style=discord.ButtonStyle.danger, emoji="📤", disabled=True, row=1)
    async def sell_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CryptoActionModal("sell", self.selected_symbol, self.cog))

# ==========================================
# КЛАС КОГА
# ==========================================

class CryptoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.market_fluctuation.start()
        self.track_crypto_history.start()

    def get_default_market(self):
        return {
            "BUB": {
                "name": "BubCoin", 
                "price": 5000, 
                "owner": "None", 
                "volatility": 0.02,
                "total_trades": 0,
                "history": [] 
            }
        }

    def apply_market_impact(self, market, symbol, amount, is_buy=True):
        if symbol not in market: return market
        
        impact_factor = 0.001 
        change = min(amount * impact_factor, 0.40)
        
        if is_buy:
            market[symbol]["price"] = int(market[symbol]["price"] * (1 + change))
        else:
            market[symbol]["price"] = int(market[symbol]["price"] * (1 - change))
            
        market[symbol]["price"] = max(100, market[symbol]["price"])
        market[symbol]["total_trades"] = market[symbol].get("total_trades", 0) + 1
        return market

    @tasks.loop(minutes=15)
    async def market_fluctuation(self):
        """Рандомна зміна ціни кожні 15 хвилин"""
        if not os.path.exists("server_data"): return
        for guild_id_str in os.listdir("server_data"):
            try:
                guild_id = int(guild_id_str)
                market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
                if not market: continue

                for symbol in market:
                    trend = random.uniform(-0.015, 0.016)
                    vol = market[symbol].get("volatility", 0.02)
                    noise = random.uniform(-vol, vol)
                    market[symbol]["price"] = max(10, int(market[symbol]["price"] * (1 + trend + noise)))

                save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
            except Exception as e:
                logger.error(f"Помилка флуктуації ринку {guild_id_str}: {e}")

    @tasks.loop(time=SAVE_TIMES)
    async def track_crypto_history(self):
        """Зберігає поточну ціну в історію кожні 2 години рівно о 00:00, 02:00, 04:00..."""
        if not os.path.exists("server_data"): return
        current_time = int(time.time())
        week_ago = current_time - (7 * 24 * 3600) 
        
        for guild_id_str in os.listdir("server_data"):
            try:
                guild_id = int(guild_id_str)
                market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
                if not market: continue
                
                updated = False
                for symbol, info in market.items():
                    if "history" not in info:
                        info["history"] = []
                        
                    info["history"].append({
                        "time": current_time,
                        "price": info["price"]
                    })
                    
                    info["history"] = [pt for pt in info["history"] if pt["time"] >= week_ago]
                    updated = True
                    
                if updated:
                    save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
                    logger.info(f"✅ Історія крипти для гільдії {guild_id} успішно збережена за графіком.")
                    
            except Exception as e:
                logger.error(f"Помилка запису історії крипти {guild_id_str}: {e}")

    @track_crypto_history.before_loop
    async def before_track_history(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="crypto", description="Курси валют та торгівля")
    @app_commands.guild_only()
    async def crypto(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        guild_id = interaction.guild.id
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        
        if not market:
            market = self.get_default_market()
            save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
        
        embed = discord.Embed(title="📊 Крипто-Біржа", color=0xF2A900)
        embed.set_footer(text="Ціни змінюються кожні 15 хв залежно від попиту")

        for symbol, info in market.items():
            price = info["price"]
            buy_p = int(price * (1 + config.get("buy_commission", 0.05)))
            sell_p = int(price * (1 - config.get("sell_commission", 0.05) - config.get("market_spread", 0.10)))
            
            embed.add_field(
                name=f"{info['name']} ({symbol})",
                value=f"📈 Курс: `{price} AC`\n📥 Купівля: `{buy_p}`\n📤 Продаж: `{sell_p}`",
                inline=True
            )
            
        chart_buffer = await asyncio.to_thread(generate_crypto_chart, market)
        file = discord.File(chart_buffer, filename="crypto_chart.png")
        embed.set_image(url="attachment://crypto_chart.png")
        
        await interaction.followup.send(embed=embed, file=file, view=CryptoMarketView(self, market))

    @app_commands.command(name="create_crypto", description="Створити свою валюту (50,000 AC)")
    @app_commands.guild_only()
    async def create_crypto(self, interaction: discord.Interaction, symbol: str, name: str):
        symbol = symbol.upper()
        if len(symbol) > 4 or not symbol.isalpha():
            return await interaction.response.send_message("❌ Символ має містити 1-4 літери!", ephemeral=True)
            
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        
        uid = str(interaction.user.id)
        user = data.get(uid, {"balance": 0})

        if user.get("balance", 0) < 50000:
            return await interaction.response.send_message("❌ Створення валюти коштує 50,000 AC готівкою.", ephemeral=True)
        
        if symbol in market:
            return await interaction.response.send_message("❌ Цей символ вже використовується.", ephemeral=True)

        user["balance"] -= 50000
        config["server_bank"] = config.get("server_bank", 0) + 50000
        
        market[symbol] = {
            "name": name,
            "price": 1000,
            "owner": interaction.user.id,
            "volatility": 0.05,
            "total_trades": 0,
            "history": [{"time": int(time.time()), "price": 1000}] 
        }
        
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        
        await interaction.response.send_message(f"Вітаємо! Валюта **{name} ({symbol})** тепер на біржі!")

    @app_commands.command(name="pay_crypto", description="Переказати криптовалюту іншому гравцю")
    @app_commands.describe(
        member="Кому переказати?",
        symbol="Символ валюти (наприклад: BUB)",
        amount="Кількість (наприклад: 1.5)"
    )
    @app_commands.guild_only()
    async def pay_crypto(self, interaction: discord.Interaction, member: discord.User, symbol: str, amount: float):
        if amount <= 0:
            return await interaction.response.send_message("❌ Кількість має бути більшою за 0!", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("❌ Ви не можете переказати крипту самому собі.", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("❌ Неможливо переказати крипту боту.", ephemeral=True)

        symbol = symbol.upper()
        guild_id = interaction.guild.id
        
        data = load_guild_json(guild_id, DATA_FILE)
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        
        if symbol not in market:
            return await interaction.response.send_message(f"❌ Валюту **{symbol}** не знайдено на біржі.", ephemeral=True)

        sender_id = str(interaction.user.id)
        receiver_id = str(member.id)

        if sender_id not in data:
            data[sender_id] = {"balance": 0, "crypto": {}}
        if receiver_id not in data:
            data[receiver_id] = {"balance": 0, "crypto": {}}

        sender = data[sender_id]
        receiver = data[receiver_id]

        sender_crypto_balance = sender.get("crypto", {}).get(symbol, 0)
        
        if sender_crypto_balance < amount:
            return await interaction.response.send_message(f"❌ У вас недостатньо **{symbol}**! Ваш баланс: `{sender_crypto_balance}`.", ephemeral=True)

        sender["crypto"][symbol] -= amount
        
        receiver.setdefault("crypto", {})[symbol] = receiver["crypto"].get(symbol, 0) + amount

        save_guild_json(guild_id, DATA_FILE, data)

        await interaction.response.send_message(f"💸 Ви успішно переказали **{amount} {symbol}** гравцю {member.mention}!")

    @app_commands.command(name="delete_crypto", description="[Адмін] Видалити валюту ")
    @app_commands.guild_only()
    async def delete_crypto(self, interaction: discord.Interaction, symbol: str):
        await interaction.response.defer()
        
        guild_id = interaction.guild.id
        symbol = symbol.upper()
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        
        if symbol not in market:
            return await interaction.followup.send("❌ Валюту не знайдено.")

        if not (interaction.user.guild_permissions.administrator or interaction.user.id == market[symbol].get("owner")):
            return await interaction.followup.send("❌ У вас немає прав на видалення цієї валюти.")

        data = load_guild_json(guild_id, DATA_FILE)
        price = market[symbol]["price"]
        count = 0

        for uid in data:
            if "crypto" in data[uid] and symbol in data[uid]["crypto"]:
                amt = data[uid]["crypto"].pop(symbol)
                compensation = int(amt * price)
                data[uid]["balance"] = data[uid].get("balance", 0) + compensation
                count += 1

        del market[symbol]
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
        
        await interaction.followup.send(f"🗑️ Валюту **{symbol}** видалено. Виплачено компенсацію {count} гравцям.")

async def setup(bot):
    await bot.add_cog(CryptoCog(bot))