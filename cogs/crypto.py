import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, time, random, logging
import io
import asyncio
from datetime import datetime, timezone, time as dt_time
from matplotlib import pyplot as plt
import pandas as pd
import mplfinance as mpf
from utils import load_guild_json, save_guild_json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CryptoBot")

SAVE_TIMES = [dt_time(hour=h, minute=0, tzinfo=timezone.utc) for h in range(0, 24, 2)]
DATA_FILE = "users.json"
ECONOMY_CONFIG = "economy_config.json"
CRYPTO_MARKET_FILE = "crypto_market.json"

def generate_ohlc_chart(market_data: dict, symbol: str) -> io.BytesIO:
    """Генерує свічковий графік (мінімалізм, світлі пастельні кольори 🌿)"""
    info = market_data.get(symbol)
    
    if not info or "history" not in info or len(info["history"]) < 2:
        fig, ax = mpf.plot(pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume']), returnfig=True)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', facecolor='#FDFCFB')
        plt.close(fig)
        buf.seek(0)
        return buf

    df = pd.DataFrame(info["history"])
    df['Date'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('Date', inplace=True)
    
    mc = mpf.make_marketcolors(
        up='#A8E6CF',  
        down='#FF8B94',
        edge='inherit',
        wick='black',
        volume='in',
        ohlc='i'
    )
    
    style = mpf.make_mpf_style(
        marketcolors=mc, 
        gridstyle=':', 
        gridcolor='#E0E0E0',
        facecolor='#FDFCFB', 
        figcolor='#FDFCFB'
    )

    buf = io.BytesIO()
    mpf.plot(
        df, type='candle', style=style, 
        title=f"\nWoodland Rise Exchange 🌿\n{info['name']} ({symbol})", 
        ylabel='Ціна (AC)', volume=True, ylabel_lower='Обсяг торгів',
        savefig=dict(fname=buf, dpi=100, bbox_inches='tight', facecolor='#FDFCFB'),
        figsize=(10, 5), tight_layout=True
    )
    buf.seek(0)
    return buf

class CryptoActionModal(discord.ui.Modal):
    """ТВІЙ ОРИГІНАЛЬНИЙ КЛАС ДЛЯ РИНКОВОЇ КУПІВЛІ/ПРОДАЖУ З УСІМА ПОДАТКАМИ"""
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
        current_time = int(time.time()) 
        
        try:
            amount = float(val_str)
        except ValueError:
            return await interaction.response.send_message("Будь ласка, введіть коректне число!", ephemeral=True)
            
        if amount < 0.001:
            return await interaction.response.send_message("Мінімальна кількість для торгівлі: 0.001", ephemeral=True)

        data = load_guild_json(guild_id, DATA_FILE)
        uid = str(interaction.user.id)
        
        if uid not in data:
            data[uid] = {"balance": 0, "crypto": {}}
        user = data[uid]

        if self.action == "buy":
            last_buy = user.get("last_buy_action", 0)
            if current_time - last_buy < 10:
                return await interaction.response.send_message(f"⏳ Занадто швидко! Зачекайте ще {10 - (current_time - last_buy)} сек.", ephemeral=True)
        else:
            last_sell = user.get("last_sell_action", 0)
            if current_time - last_sell < 30:
                return await interaction.response.send_message(f"⏳ Ринок перевантажено! Зачекайте ще {30 - (current_time - last_sell)} сек.", ephemeral=True)

        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)

        if self.symbol not in market:
            return await interaction.response.send_message("Валюту не знайдено на біржі.", ephemeral=True)

        price = market[self.symbol]["price"]
        owner_id = str(market[self.symbol].get("owner"))

        if self.action == "buy":
            buy_commission = config.get("buy_commission", 0.05)
            total_cost = int(price * amount * (1 + buy_commission))
            
            if total_cost < 1:
                return await interaction.response.send_message("Сума угоди занадто мала! Витрати мають становити мінімум 1 AC.", ephemeral=True)
            
            if user.get("balance", 0) < total_cost:
                return await interaction.response.send_message(f"Недостатньо AC! Треба `{total_cost}`.", ephemeral=True)

            commission_amount = int(price * amount * buy_commission)
            owner_share = int(price * amount * 0.01) if owner_id != "None" else 0
            bank_share = commission_amount - owner_share

            user["balance"] -= total_cost
            config["server_bank"] = config.get("server_bank", 0) + bank_share
            
            if owner_id != "None" and owner_id in data:
                data[owner_id]["balance"] = data[owner_id].get("balance", 0) + owner_share
            
            user.setdefault("crypto", {})[self.symbol] = user["crypto"].get(self.symbol, 0) + amount
            user.setdefault("crypto_timestamps", {})[self.symbol] = current_time
            user["last_buy_action"] = current_time 

            msg = f"📥 Куплено **{amount} {self.symbol}** за `{total_cost} AC`."

        else:
            if self.symbol not in user.get("crypto", {}) or user["crypto"][self.symbol] < amount:
                return await interaction.response.send_message("Недостатньо криптовалюти для продажу.", ephemeral=True)

            sell_commission = config.get("sell_commission", 0.05)
            market_spread = config.get("market_spread", 0.10)
            base_sell = int(price * amount * (1 - sell_commission - market_spread))
            
            if base_sell < 1:
                return await interaction.response.send_message("Сума продажу занадто мала! Ви маєте отримати мінімум 1 AC.", ephemeral=True)
            
            owner_share = int(price * amount * 0.01) if owner_id != "None" else 0
            
            last_buy = user.get("crypto_timestamps", {}).get(self.symbol, 0)
            penalty_msg = ""
            if (current_time - last_buy) < 7200:
                penalty = int(base_sell * config.get("paper_hands_tax", 0.15))
                base_sell -= penalty
                config["server_bank"] = config.get("server_bank", 0) + penalty
                penalty_msg = f"\n⚠️ Штраф (Paper Hands): -`{penalty} AC`"

            user["crypto"][self.symbol] -= amount
            user["balance"] += base_sell
            
            market[self.symbol]["burned"] = market[self.symbol].get("burned", 0) + (amount * (sell_commission / 2))
            
            if owner_id != "None" and owner_id in data:
                data[owner_id]["balance"] = data[owner_id].get("balance", 0) + owner_share

            user["last_sell_action"] = current_time
            msg = f"📤 Продано **{amount} {self.symbol}** за `{base_sell} AC`.{penalty_msg}"

        market = self.cog.apply_market_impact(market, self.symbol, amount, is_buy=(self.action == "buy"))

        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
        
        await interaction.response.send_message(msg, ephemeral=True)

class LimitOrderModal(discord.ui.Modal):
    def __init__(self, action: str, symbol: str, cog: commands.Cog):
        super().__init__(title=f"Лімітний ордер: {symbol} ({'Купівля' if action == 'buy' else 'Продаж'})")
        self.action = action
        self.symbol = symbol
        self.cog = cog

        self.amount_input = discord.ui.TextInput(label="Кількість монет", placeholder="1.5", required=True)
        self.price_input = discord.ui.TextInput(label="Бажана ціна за 1 монету (AC)", placeholder="1050", required=True)
        
        self.add_item(self.amount_input)
        self.add_item(self.price_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = float(self.amount_input.value.replace(',', '.'))
            price = int(self.price_input.value)
        except ValueError:
            return await interaction.response.send_message("❌ Невірний формат чисел.", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        uid = str(interaction.user.id)
        user = data.setdefault(uid, {"balance": 0, "crypto": {}})
        
        if self.action == "buy":
            total_cost = int(amount * price)
            if user.get("balance", 0) < total_cost:
                return await interaction.response.send_message(f"Недостатньо AC! Треба {total_cost}.", ephemeral=True)
            user["balance"] -= total_cost 
        else:
            if user.get("crypto", {}).get(self.symbol, 0) < amount:
                return await interaction.response.send_message(f"Недостатньо {self.symbol} для продажу.", ephemeral=True)
            user["crypto"][self.symbol] -= amount 

        order_book = market[self.symbol].setdefault("order_book", {"buy": [], "sell": []})
        order = {"uid": uid, "amount": amount, "price": price, "timestamp": int(time.time())}
        order_book[self.action].append(order)

        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
        await interaction.response.send_message(f"📋 Лімітний ордер успішно створено!", ephemeral=True)

class StakingModal(discord.ui.Modal):
    def __init__(self, symbol: str, cog: commands.Cog):
        super().__init__(title=f"Стейкінг {symbol}")
        self.symbol = symbol
        self.amount_input = discord.ui.TextInput(label="Скільки монет заблокувати?", placeholder="10", required=True)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = float(self.amount_input.value.replace(',', '.'))
        except ValueError:
            return await interaction.response.send_message("❌ Невірний формат.", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        uid = str(interaction.user.id)
        user = data.get(uid, {})

        if user.get("crypto", {}).get(self.symbol, 0) < amount:
            return await interaction.response.send_message("Недостатньо монет на балансі.", ephemeral=True)

        user["crypto"][self.symbol] -= amount
        stake_record = user.setdefault("staking", {}).setdefault(self.symbol, {"amount": 0, "start_time": int(time.time())})
        stake_record["amount"] += amount
        stake_record["start_time"] = int(time.time())

        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"Ви заблокували {amount} {self.symbol} у стейкінг! Відсотки капають щодня.", ephemeral=True)

class CoinDetailView(discord.ui.View):
    def __init__(self, cog: commands.Cog, symbol: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.symbol = symbol

    @discord.ui.button(label="Купити (Ринок)", style=discord.ButtonStyle.success, emoji="📥", row=0)
    async def buy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CryptoActionModal("buy", self.symbol, self.cog))

    @discord.ui.button(label="Продати (Ринок)", style=discord.ButtonStyle.danger, emoji="📤", row=0)
    async def sell_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CryptoActionModal("sell", self.symbol, self.cog))

    @discord.ui.button(label="Купити (Ліміт)", style=discord.ButtonStyle.secondary, emoji="🕒", row=1)
    async def limit_buy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LimitOrderModal("buy", self.symbol, self.cog))

    @discord.ui.button(label="Продати (Ліміт)", style=discord.ButtonStyle.secondary, emoji="🕒", row=1)
    async def limit_sell_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LimitOrderModal("sell", self.symbol, self.cog))

    @discord.ui.button(label="Стейкінг", style=discord.ButtonStyle.primary, emoji="🌳", row=2)
    async def stake_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StakingModal(self.symbol, self.cog))

class CryptoSearchModal(discord.ui.Modal, title='Пошук Активу'):
    symbol_input = discord.ui.TextInput(label='Введіть тікер (напр. BUB)', max_length=4, required=True)

    def __init__(self, cog: commands.Cog, market: dict):
        super().__init__()
        self.cog = cog
        self.market = market

    async def on_submit(self, interaction: discord.Interaction):
        symbol = self.symbol_input.value.upper()
        if symbol not in self.market:
            return await interaction.response.send_message(f"🍃 Валюту **{symbol}** не знайдено.", ephemeral=True)
        
        info = self.market[symbol]
        embed = discord.Embed(title=f"Деталі: {info['name']} ({symbol})", color=0xA8E6CF)
        
        circulating = info.get("circulating_supply", 0)
        max_sup = info.get("max_supply", "Необмежено")
        burned = round(info.get("burned", 0), 2)
        
        embed.add_field(name="Поточний курс", value=f"`{info['price']} AC`", inline=True)
        embed.add_field(name="Емісія", value=f"`{circulating} / {max_sup}`", inline=True)
        embed.add_field(name="Спалено 🔥", value=f"`{burned}`", inline=True)
        
        chart_buffer = await asyncio.to_thread(generate_ohlc_chart, self.market, symbol)
        file = discord.File(chart_buffer, filename=f"{symbol}_chart.png")
        embed.set_image(url=f"attachment://{symbol}_chart.png")

        await interaction.response.send_message(embed=embed, file=file, view=CoinDetailView(self.cog, symbol), ephemeral=True)

class CryptoDashboardView(discord.ui.View):
    def __init__(self, cog: commands.Cog, market: dict):
        super().__init__(timeout=None)
        self.cog = cog
        self.market = market

    @discord.ui.button(label="🔍 Знайти валюту", style=discord.ButtonStyle.secondary)
    async def search_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CryptoSearchModal(self.cog, self.market))

class AdvancedCryptoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.market_fluctuation.start()
        self.track_ohlc_history.start()
        self.process_limit_orders.start()
        self.process_staking_rewards.start()
        self.macroeconomic_news.start()

    def get_default_market(self):
        return {
            "BUB": {
                "name": "BubCoin", 
                "price": 1000, 
                "owner": "None", 
                "volatility": 0.02,
                "momentum": 0.0,
                "market_heat": 0.0,
                "volume_buy": 0,    
                "volume_sell": 0,   
                "total_trades": 0,
                "max_supply": 100000,
                "circulating_supply": 0,
                "burned": 0,
                "order_book": {"buy": [], "sell": []},
                "history": [] 
            }
        }

    def apply_market_impact(self, market, symbol, amount, is_buy=True):
        """Твоя оригінальна логіка впливу на ринок"""
        if symbol not in market: return market
        
        info = market[symbol]
        current_price = info["price"]
        trade_value = amount * current_price
        
        liquidity = 200000 + (info.get("total_trades", 0) * 2000)
        impact = (trade_value / liquidity) * 1.5
        impact = max(0.005, min(impact, 0.50)) 
        
        if is_buy:
            info["price"] = int(current_price * (1 + impact))
            info["volume_buy"] = info.get("volume_buy", 0) + trade_value
            info["momentum"] = info.get("momentum", 0.0) + (impact * 0.8)
            info["circulating_supply"] = info.get("circulating_supply", 0) + amount
        else:
            info["price"] = int(current_price * (1 - impact))
            info["volume_sell"] = info.get("volume_sell", 0) + trade_value
            info["momentum"] = info.get("momentum", 0.0) - (impact * 1.2)
            
        info["price"] = max(50, info["price"])
        info["total_trades"] = info.get("total_trades", 0) + 1
        info["momentum"] = max(-0.25, min(info["momentum"], 0.25))
        info["market_heat"] = min(1.0, info.get("market_heat", 0.0) + 0.15 + (impact * 3))
        
        return market

    @tasks.loop(minutes=15)
    async def market_fluctuation(self):
        """Фоновий ШІ-аналіз активності"""
        if not os.path.exists("server_data"): return

        for guild_id_str in os.listdir("server_data"):
            try:
                guild_id = int(guild_id_str)
                market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
                if not market: continue

                for symbol, info in market.items():
                    momentum = info.get("momentum", 0.0)
                    base_volatility = info.get("volatility", 0.02)
                    heat = info.get("market_heat", 0.0)
                    
                    current_volatility = base_volatility * (0.2 + 0.8 * heat)
                    drift = random.uniform(-0.001, 0.001) * max(1.0, heat)
                    noise = random.uniform(-current_volatility, current_volatility)
                    
                    total_multiplier = 1.0 + momentum + noise + drift
                    info["price"] = max(10, int(info["price"] * total_multiplier))
                    info["market_heat"] = heat * 0.85 
                    
                    if random.random() < 0.25:
                        info["momentum"] = -momentum * random.uniform(0.5, 1.2) + random.uniform(-0.015, 0.02)
                    else:
                        info["momentum"] *= 0.7 
                    
                    info["momentum"] = max(-0.25, min(info["momentum"], 0.25))

                save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
            except Exception as e:
                logger.error(f"Помилка флуктуації ринку: {e}")

    @tasks.loop(minutes=30)
    async def track_ohlc_history(self):
        """Збереження свічок (Open, High, Low, Close) кожні 30 хвилин"""
        if not os.path.exists("server_data"): return
        current_time = int(time.time())
        
        for guild_id_str in os.listdir("server_data"):
            try:
                guild_id = int(guild_id_str)
                market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
                if not market: continue
                
                for symbol, info in market.items():
                    info.setdefault("history", [])
                    current_price = info["price"]
                    last_price = info["history"][-1]["Close"] if info["history"] else current_price
                    
                    vol = info.get("volatility", 0.02) * current_price
                    high = max(current_price, last_price) + random.uniform(0, vol)
                    low = min(current_price, last_price) - random.uniform(0, vol)
                    
                    info["history"].append({
                        "time": current_time,
                        "Open": last_price,
                        "High": high,
                        "Low": low,
                        "Close": current_price,
                        "Volume": info.get("volume_buy", 0) + info.get("volume_sell", 0)
                    })
                    
                    info["volume_buy"] = 0
                    info["volume_sell"] = 0
                    info["history"] = info["history"][-100:] 
                    
                save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
            except Exception as e:
                logger.error(f"Помилка історії OHLC: {e}")

    @tasks.loop(minutes=5)
    async def process_limit_orders(self):
        """Механізм зведення лімітних ордерів"""
        if not os.path.exists("server_data"): return
        
        for guild_id_str in os.listdir("server_data"):
            guild_id = int(guild_id_str)
            market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
            data = load_guild_json(guild_id, DATA_FILE)
            if not market: continue

            for symbol, info in market.items():
                order_book = info.get("order_book", {"buy": [], "sell": []})
                current_price = info["price"]
                
                for buy_order in order_book["buy"][:]:
                    if current_price <= buy_order["price"]:
                        uid = buy_order["uid"]
                        user = data.get(uid)
                        if user:
                            user.setdefault("crypto", {})[symbol] = user.get("crypto", {}).get(symbol, 0) + buy_order["amount"]
                            order_book["buy"].remove(buy_order)
                
                for sell_order in order_book["sell"][:]:
                    if current_price >= sell_order["price"]:
                        uid = sell_order["uid"]
                        user = data.get(uid)
                        if user:
                            user["balance"] = user.get("balance", 0) + int(sell_order["amount"] * current_price)
                            order_book["sell"].remove(sell_order)

            save_guild_json(guild_id, DATA_FILE, data)
            save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)

    @tasks.loop(hours=24)
    async def process_staking_rewards(self):
        """Щоденне нарахування відсотків за стейкінг (APY)"""
        if not os.path.exists("server_data"): return
        
        for guild_id_str in os.listdir("server_data"):
            guild_id = int(guild_id_str)
            data = load_guild_json(guild_id, DATA_FILE)
            market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
            
            for uid, user in data.items():
                if "staking" not in user: continue
                for symbol, stake_info in user["staking"].items():
                    if symbol not in market: continue
                    daily_reward_pct = 0.05 / 365 # 5% річних
                    reward_amount = stake_info["amount"] * daily_reward_pct
                    user.setdefault("crypto", {})[symbol] = user.get("crypto", {}).get(symbol, 0) + reward_amount
                    
            save_guild_json(guild_id, DATA_FILE, data)

    @tasks.loop(hours=48)
    async def macroeconomic_news(self):
        """Глобальні економічні події"""
        events = [
            {"msg": "🌟 Впроваджено нові технології! Ринок зростає.", "impact": 0.15},
            {"msg": "⚠️ Регулятори посилюють правила. Довіра падає.", "impact": -0.20},
            {"msg": "🌿 Спокійний період. Активи стабілізуються.", "impact": 0.0}
        ]
        
        for guild_id_str in os.listdir("server_data"):
            guild_id = int(guild_id_str)
            market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
            if not market: continue
            
            event = random.choice(events)
            if event["impact"] != 0.0:
                for symbol, info in market.items():
                    info["momentum"] = info.get("momentum", 0) + event["impact"]
                    info["market_heat"] = 1.0 
                save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)

    @market_fluctuation.before_loop
    @track_ohlc_history.before_loop
    @process_limit_orders.before_loop
    @process_staking_rewards.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="market", description="Відкрити головну панель економічного хабу")
    @app_commands.guild_only()
    async def market_dashboard(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        
        if not market:
            market = self.get_default_market()
            save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)

        embed = discord.Embed(
            title="🌿 Woodland Rise: Економічний Хаб", 
            description="Огляд поточного стану ринку. Натисніть кнопку, щоб знайти актив для торгівлі.",
            color=0xFDFCFB
        )
        
        sorted_market = sorted(market.items(), key=lambda x: x[1]['price'], reverse=True)[:5]
        for symbol, info in sorted_market:
            trend = "📈" if info.get("momentum", 0) > 0 else "📉"
            embed.add_field(
                name=f"{info['name']} ({symbol}) {trend}",
                value=f"Курс: `{info['price']} AC`",
                inline=False
            )

        await interaction.response.send_message(embed=embed, view=CryptoDashboardView(self, market))

    @app_commands.command(name="create_crypto", description="Створити свою валюту з лімітом емісії (100,000 AC)")
    @app_commands.guild_only()
    async def create_crypto(self, interaction: discord.Interaction, symbol: str, name: str, max_supply: int = 100000):
        symbol = symbol.upper()
        if len(symbol) > 4 or not symbol.isalpha():
            return await interaction.response.send_message("Символ має містити 1-4 літери!", ephemeral=True)
            
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        
        uid = str(interaction.user.id)
        user = data.get(uid, {"balance": 0})

        if user.get("balance", 0) < 100000:
            return await interaction.response.send_message("Створення валюти коштує 100,000 AC готівкою.", ephemeral=True)
        
        if symbol in market:
            return await interaction.response.send_message("Цей символ вже використовується.", ephemeral=True)

        user["balance"] -= 100000
        config["server_bank"] = config.get("server_bank", 0) + 100000
        
        market[symbol] = {
            "name": name,
            "price": 1000,
            "owner": interaction.user.id,
            "volatility": 0.05,
            "momentum": 0.0,
            "market_heat": 1.0,
            "total_trades": 0,
            "max_supply": max_supply,
            "circulating_supply": 0,
            "burned": 0,
            "order_book": {"buy": [], "sell": []},
            "history": [{"time": int(time.time()), "Open": 1000, "High": 1000, "Low": 1000, "Close": 1000, "Volume": 0}] 
        }
        
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, CRYPTO_MARKET_FILE, market)
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        
        await interaction.response.send_message(f"🎉 Вітаємо! Валюта **{name} ({symbol})** з емісією {max_supply} тепер на біржі!")

    @app_commands.command(name="pay_crypto", description="Переказати криптовалюту іншому гравцю")
    @app_commands.describe(member="Кому переказати?", symbol="Символ валюти", amount="Кількість")
    @app_commands.guild_only()
    async def pay_crypto(self, interaction: discord.Interaction, member: discord.User, symbol: str, amount: float):
        if amount <= 0: return await interaction.response.send_message("Кількість має бути більшою за 0!", ephemeral=True)
        if member.id == interaction.user.id: return await interaction.response.send_message("Ви не можете переказати собі.", ephemeral=True)
        if member.bot: return await interaction.response.send_message("Неможливо переказати крипту боту.", ephemeral=True)

        symbol = symbol.upper()
        guild_id = interaction.guild.id
        
        data = load_guild_json(guild_id, DATA_FILE)
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        
        if symbol not in market:
            return await interaction.response.send_message(f"Валюту **{symbol}** не знайдено на біржі.", ephemeral=True)

        sender_id = str(interaction.user.id)
        receiver_id = str(member.id)

        sender = data.setdefault(sender_id, {"balance": 0, "crypto": {}})
        receiver = data.setdefault(receiver_id, {"balance": 0, "crypto": {}})

        sender_crypto_balance = sender.get("crypto", {}).get(symbol, 0)
        
        if sender_crypto_balance < amount:
            return await interaction.response.send_message(f"У вас недостатньо **{symbol}**!", ephemeral=True)

        sender["crypto"][symbol] -= amount
        receiver.setdefault("crypto", {})[symbol] = receiver["crypto"].get(symbol, 0) + amount

        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"💸 Ви переказали **{amount} {symbol}** гравцю {member.mention}!")

    @app_commands.command(name="delete_crypto", description="[Адмін] Видалити валюту")
    @app_commands.guild_only()
    async def delete_crypto(self, interaction: discord.Interaction, symbol: str):
        await interaction.response.defer()
        
        guild_id = interaction.guild.id
        symbol = symbol.upper()
        market = load_guild_json(guild_id, CRYPTO_MARKET_FILE)
        
        if symbol not in market:
            return await interaction.followup.send("Валюту не знайдено.")

        if not (interaction.user.guild_permissions.administrator or interaction.user.id == market[symbol].get("owner")):
            return await interaction.followup.send("У вас немає прав на видалення цієї валюти.")

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
        
        await interaction.followup.send(f"Валюту **{symbol}** видалено. Компенсацію виплачено {count} гравцям.")

async def setup(bot):
    await bot.add_cog(AdvancedCryptoCog(bot))