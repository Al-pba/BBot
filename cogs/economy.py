import io
import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import os
import logging
from PIL import Image, ImageDraw, ImageFont
from utils import load_guild_json, save_guild_json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EconomyBot")

DATA_FILE = "users.json"
ECONOMY_CONFIG = "economy_config.json"

# ==========================================
# UI ДЛЯ /bank (Модалки)
# ==========================================

class BankActionModal(discord.ui.Modal):
    def __init__(self, action: str, cog: commands.Cog):
        titles = {"dep": "🏦 Депозит", "with": "📤 Зняття готівки", "loan": "📜 Кредит"}
        super().__init__(title=titles.get(action, "Операція"))
        self.action = action
        self.cog = cog
        self.amount_input = discord.ui.TextInput(
            label="Сума AC", 
            placeholder="Введіть ціле число...", 
            required=True,
            min_length=1
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value)
        except ValueError:
            return await interaction.response.send_message("Введіть коректне ціле число!", ephemeral=True)
            
        if amount <= 0:
            return await interaction.response.send_message("Сума має бути більшою за 0!", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        user = self.cog.get_user(data, interaction.user.id)
        server_bank = config.get("server_bank", 0)

        # --- ДЕПОЗИТ ---
        if self.action == "dep":
            if user["balance"] < amount: 
                return await interaction.response.send_message("У вас недостатньо готівки!", ephemeral=True)
            
            user["balance"] -= amount
            user["bank"] += amount
            config["server_bank"] = server_bank + amount
            
            save_guild_json(guild_id, DATA_FILE, data)
            save_guild_json(guild_id, ECONOMY_CONFIG, config)
            return await interaction.response.send_message(f"Внесено **{amount} AC** на депозит. Казна поповнена!", ephemeral=True)

        # --- ЗНЯТТЯ ---
        elif self.action == "with":
            if user["bank"] < amount: 
                return await interaction.response.send_message("Мало грошей на банківському рахунку!", ephemeral=True)
            
            fee = int(amount * config.get("withdraw_fee", 0.01))
            net = amount - fee
            
            if server_bank < net: 
                return await interaction.response.send_message("⚠️ У казні зараз недостатньо готівки для видачі!", ephemeral=True)
            
            user["bank"] -= amount
            user["balance"] += net
            config["server_bank"] = server_bank - net
            
            save_guild_json(guild_id, DATA_FILE, data)
            save_guild_json(guild_id, ECONOMY_CONFIG, config)
            return await interaction.response.send_message(f"💸 Ви зняли **{net} AC** (Комісія: {fee}).", ephemeral=True)

        # --- КРЕДИТ (ЗАПИТ ПІДТВЕРДЖЕННЯ) ---
        elif self.action == "loan":
            max_loan = user.get("level", 1) * 1000
            if amount > max_loan: 
                return await interaction.response.send_message(f"Максимальний кредит банку для вашого {user.get('level', 1)} рівня — **{max_loan} AC**.", ephemeral=True)
            
            if user["bank_loan"]["amount"] > 0: 
                return await interaction.response.send_message("У вас вже є активний кредит!", ephemeral=True)
            if server_bank < amount: 
                return await interaction.response.send_message("У казні немає грошей для видачі такого кредиту.", ephemeral=True)
            
            view = LoanConfirmationView(self.cog, interaction.user.id, amount, is_bank=True)
            await interaction.response.send_message(
                f"❓ Ви справді хочете взяти кредит у банку на суму **{amount} AC** під заставу майна?", 
                view=view, 
                ephemeral=True
            )

# ==========================================
# UI Кнопки Підтвердження
# ==========================================

class RepayConfirmationView(discord.ui.View):
    def __init__(self, cog, debtor_id, creditor_id, amount, is_bank=False):
        super().__init__(timeout=60)
        self.cog = cog
        self.debtor_id = debtor_id
        self.creditor_id = creditor_id 
        self.amount = amount
        self.is_bank = is_bank

    @discord.ui.button(label="Підтвердити оплату", style=discord.ButtonStyle.success, emoji="💰")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.debtor_id:
            return await interaction.response.send_message("Це не ваше меню!", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        debtor = self.cog.get_user(data, self.debtor_id)

        if debtor["balance"] < self.amount:
            return await interaction.response.edit_message(content=f"Недостатньо готівки! Потрібно `{self.amount} AC`.", view=None)

        def evaluate_restrictions(user_obj):
            """Знімає блокування, якщо всі борги погашені"""
            has_bank_overdue = user_obj.get("bank_loan", {}).get("is_overdue", False)
            has_p2p_overdue = any(l.get("is_overdue") for l in user_obj.get("active_loans", []))
            
            if not has_bank_overdue:
                user_obj["restricted_casino"] = False
            if not has_bank_overdue and not has_p2p_overdue:
                user_obj["restricted_pay"] = False

        if self.is_bank:
            debtor["balance"] -= self.amount
            config["server_bank"] = config.get("server_bank", 0) + self.amount
            debtor["bank_loan"] = {"amount": 0, "deadline": 0, "is_overdue": False}
            evaluate_restrictions(debtor)
            msg = f"<@{self.debtor_id}> повністю повернув банку борг: **{self.amount} AC**. Обмеження рахунків знято!"
        else:
            creditor = self.cog.get_user(data, self.creditor_id)
            debtor["balance"] -= self.amount
            creditor["balance"] += self.amount
            debtor["active_loans"] = [l for l in debtor["active_loans"] if l["from_id"] != self.creditor_id]
            evaluate_restrictions(debtor)
            msg = f"Борг **{self.amount} AC** перед <@{self.creditor_id}> погашено гравцем <@{self.debtor_id}>!"

        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, ECONOMY_CONFIG, config)

        await interaction.response.edit_message(content="♻️ Транзакція успішна.", view=None)
        await interaction.channel.send(msg)

    @discord.ui.button(label="Скасувати", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Операцію скасовано.", view=None)

class LoanConfirmationView(discord.ui.View):
    def __init__(self, cog, target_id, amount, sender_id=None, days=None, is_bank=False):
        super().__init__(timeout=60)
        self.cog = cog
        self.target_id = target_id
        self.amount = amount
        self.sender_id = sender_id
        self.days = days
        self.is_bank = is_bank

    @discord.ui.button(label="Підтвердити", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message("Це не для вас!", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        borrower = self.cog.get_user(data, self.target_id)

        if self.is_bank:
            if config.get("server_bank", 0) < self.amount:
                return await interaction.response.edit_message(content="У банку закінчилися гроші!", view=None)
            
            config["server_bank"] -= self.amount
            borrower["balance"] += self.amount
            borrower["bank_loan"] = {"amount": self.amount, "deadline": int(time.time()) + (7 * 86400), "is_overdue": False}
        else:
            lender = self.cog.get_user(data, self.sender_id)
            if lender["balance"] < self.amount:
                return await interaction.response.edit_message(content="У кредитора вже недостатньо коштів для позики!", view=None)
            
            lender["balance"] -= self.amount
            borrower["balance"] += self.amount
            borrower["active_loans"].append({
                "from_id": self.sender_id, "amount": self.amount, "deadline": int(time.time()) + (self.days * 86400), "is_overdue": False
            })

        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        await interaction.response.edit_message(content="Операція успішна! Гроші нараховані.", view=None)

    @discord.ui.button(label="Відхилити", style=discord.ButtonStyle.danger, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message("Це не для вас!", ephemeral=True)
        await interaction.response.edit_message(content="Операцію скасовано або відхилено.", view=None)

class BankMenuView(discord.ui.View):
    def __init__(self, cog: commands.Cog, author_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Це не ваше меню!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Депозит", style=discord.ButtonStyle.success, emoji="📥")
    async def dep(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BankActionModal("dep", self.cog))

    @discord.ui.button(label="Зняти", style=discord.ButtonStyle.secondary, emoji="📤")
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BankActionModal("with", self.cog))

    @discord.ui.button(label="Взяти кредит", style=discord.ButtonStyle.primary, emoji="📜")
    async def loan(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BankActionModal("loan", self.cog))

# ==========================================
# ОСНОВНИЙ COG КЛАС
# ==========================================

class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bank_tax_loop.start()
        self.loan_checker_loop.start()

    def get_user(self, data, uid):
        uid = str(uid)
        if uid not in data:
            data[uid] = {
                "balance": 100, 
                "bank": 0, 
                "bank_loan": {"amount": 0, "deadline": 0, "is_overdue": False},
                "active_loans": []
            }
        data[uid].setdefault("bank", 0)
        data[uid].setdefault("balance", 0)
        data[uid].setdefault("level", 1)
        data[uid].setdefault("restricted_pay", False)
        data[uid].setdefault("restricted_casino", False)
        data[uid].setdefault("bank_loan", {"amount": 0, "deadline": 0, "is_overdue": False})
        data[uid].setdefault("active_loans", [])
        return data[uid]

    def get_reserve_status(self, balance: int):
        if balance >= 1000000: return "💎 Ідеальний (Профіцит)"
        if balance >= 500000: return "🟢 Високий"
        if balance >= 100000: return "🟡 Стабільний"
        if balance >= 20000: return "🟠 Низький"
        return "🔴 КРИТИЧНИЙ (ДЕФОЛТ)"

    @tasks.loop(hours=24)
    async def bank_tax_loop(self):
        if not os.path.exists("server_data"): return
        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                data = load_guild_json(guild_id, DATA_FILE)
                config = load_guild_json(guild_id, ECONOMY_CONFIG)
                
                tax_rate = config.get("bank_tax_rate", 0.01) 
                
                updated = False
                for uid in data:
                    if data[uid].get("bank", 0) > 0:
                        tax = int(data[uid]["bank"] * tax_rate) 
                        if tax > 0:
                            data[uid]["bank"] -= tax
                            config["server_bank"] = config.get("server_bank", 0) + tax
                            updated = True
                if updated:
                    save_guild_json(guild_id, DATA_FILE, data)
                    save_guild_json(guild_id, ECONOMY_CONFIG, config)
            except Exception as e:
                logger.error(f"Помилка в податковому циклі для гільдії {gid}: {e}")

    @tasks.loop(hours=1)
    async def loan_checker_loop(self):
        """Жорстка перевірка боргів: знімає гроші, якщо не вистачає — блокує рахунки"""
        if not os.path.exists("server_data"): return
        current_time = int(time.time())
        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                data = load_guild_json(guild_id, DATA_FILE)
                config = load_guild_json(guild_id, ECONOMY_CONFIG)
                updated = False
                
                for uid in data:
                    u = data[uid]
                    
                    loan = u.get("bank_loan", {"amount": 0, "deadline": 0, "is_overdue": False})
                    if loan["amount"] > 0 and current_time > loan["deadline"] and not loan.get("is_overdue"):
                        penalty = int(loan["amount"] * 1.5)
                        
                        if u.get("balance", 0) >= penalty:
                            u["balance"] -= penalty
                            config["server_bank"] = config.get("server_bank", 0) + penalty
                            u["bank_loan"] = {"amount": 0, "deadline": 0, "is_overdue": False}
                        else:
                            taken = u.get("balance", 0)
                            u["balance"] = 0
                            config["server_bank"] = config.get("server_bank", 0) + taken
                            
                            u["bank_loan"]["amount"] = penalty - taken
                            u["bank_loan"]["is_overdue"] = True
                            u["restricted_pay"] = True
                            u["restricted_casino"] = True
                        updated = True

                    active_loans = []
                    for l in u.get("active_loans", []):
                        if current_time > l["deadline"] and not l.get("is_overdue"):
                            penalty = int(l["amount"] * 1.5)
                            creditor_id = str(l["from_id"])
                            if creditor_id not in data:
                                data[creditor_id] = {"balance": 0}
                            
                            if u.get("balance", 0) >= penalty:
                                u["balance"] -= penalty
                                data[creditor_id]["balance"] = data[creditor_id].get("balance", 0) + penalty
                            else:
                                taken = u.get("balance", 0)
                                u["balance"] = 0
                                data[creditor_id]["balance"] = data[creditor_id].get("balance", 0) + taken
                                
                                l["amount"] = penalty - taken
                                l["is_overdue"] = True
                                u["restricted_pay"] = True
                                active_loans.append(l)
                            updated = True
                        else:
                            active_loans.append(l)
                            
                    u["active_loans"] = active_loans

                if updated:
                    save_guild_json(guild_id, DATA_FILE, data)
                    save_guild_json(guild_id, ECONOMY_CONFIG, config)
            except Exception as e:
                logger.error(f"Помилка в циклі перевірки кредитів для {gid}: {e}")

    @app_commands.command(name="bank", description="Меню вашого банківського рахунку")
    @app_commands.guild_only()
    async def bank_menu(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user = self.get_user(data, interaction.user.id)
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        
        embed = discord.Embed(title=f"🏛️ Банк: {interaction.user.display_name}", color=0x2ecc71)
        embed.add_field(name="Ваш Рахунок", value=f"`{user['bank']} AC`", inline=True)
        embed.add_field(name="Готівка", value=f"`{user['balance']} AC`", inline=True)
        embed.add_field(name="Казна", value=f"`{config.get('server_bank', 0)} AC`", inline=True)
        
        if user["bank_loan"]["amount"] > 0:
            status = "🚨 ПРОСТРОЧЕНО" if user["bank_loan"].get("is_overdue") else "⏳ Активний"
            embed.add_field(name=f"⚠️ Борг банку ({status})", value=f"`{user['bank_loan']['amount']} AC`", inline=False)
            
        if user.get("restricted_pay") or user.get("restricted_casino"):
            embed.description = "🛑 **Ваші рахунки обмежено через борги!** Погасіть їх через `/pay_loan` або `/pay_debt`."
            embed.color = 0xe74c3c
        
        await interaction.response.send_message(embed=embed, view=BankMenuView(self, interaction.user.id), ephemeral=True)

    @app_commands.command(name="pay", description="Переказати готівку іншому гравцю")
    @app_commands.guild_only()
    async def pay(self, interaction: discord.Interaction, member: discord.User, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("Сума має бути більшою за 0.", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("Ви не можете переказати гроші самому собі.", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("Неможливо переказати гроші боту.", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        s = self.get_user(data, interaction.user.id)
        r = self.get_user(data, member.id)

        if s.get("restricted_pay"):
            return await interaction.response.send_message("Ваші рахунки заблоковано через несплачені борги! Ви не можете переказувати кошти.", ephemeral=True)

        if s["balance"] < amount:
            return await interaction.response.send_message("У вас недостатньо готівки!", ephemeral=True)

        s["balance"] -= amount
        r["balance"] += amount
        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"Успішно переказано **{amount} AC** користувачу {member.mention}.")

    @app_commands.command(name="lend", description="Запропонувати гроші в борг іншому гравцю")
    @app_commands.guild_only()
    async def lend(self, interaction: discord.Interaction, member: discord.User, amount: int, days: int):
        if amount <= 0 or days < 1:
            return await interaction.response.send_message("Некоректна сума або термін (мінімум 1 день).", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("Ви не можете позичити самому собі.", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("Боти не беруть у борг.", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        lender = self.get_user(data, interaction.user.id)

        if lender.get("restricted_pay"):
            return await interaction.response.send_message("Ваші рахунки заблоковано через борги! Ви не можете давати позики.", ephemeral=True)

        if lender["balance"] < amount:
            return await interaction.response.send_message(f"У вас немає такої суми готівкою!", ephemeral=True)

        view = LoanConfirmationView(self, member.id, amount, sender_id=interaction.user.id, days=days, is_bank=False)
        await interaction.response.send_message(
            f"🤝 {member.mention}, {interaction.user.mention} пропонує вам **{amount} AC** у борг на **{days}** днів. Згодні?",
            view=view
        )

    @app_commands.command(name="pay_debt", description="Повернути борг іншому гравцю")
    @app_commands.guild_only()
    async def pay_debt(self, interaction: discord.Interaction, member: discord.User):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        debtor_data = self.get_user(data, interaction.user.id)

        loan_entry = next((l for l in debtor_data["active_loans"] if l["from_id"] == member.id), None)
        if not loan_entry:
            return await interaction.response.send_message(f"Ви нічого не винні {member.display_name}.", ephemeral=True)

        view = RepayConfirmationView(self, interaction.user.id, member.id, loan_entry["amount"], is_bank=False)
        await interaction.response.send_message(f"💰 Ваш борг перед {member.mention}: **{loan_entry['amount']} AC**. Повернути?", view=view, ephemeral=True)

    @app_commands.command(name="pay_loan", description="Погасити кредит банку")
    @app_commands.guild_only()
    async def pay_loan(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        user_data = self.get_user(data, interaction.user.id)
        
        loan_amount = user_data["bank_loan"]["amount"]
        if loan_amount <= 0:
            return await interaction.response.send_message("У вас немає боргів перед банком.", ephemeral=True)

        view = RepayConfirmationView(self, interaction.user.id, None, loan_amount, is_bank=True)
        await interaction.response.send_message(f"🏦 Ваш борг банку: **{loan_amount} AC**. Бажаєте погасити?", view=view, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Топ найбагатших гравців")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        
        active_users = []
        for uid, udata in data.items():
            member = interaction.guild.get_member(int(uid))
            if member:
                total_wealth = udata.get("balance", 0) + udata.get("bank", 0)
                active_users.append((member, total_wealth))

        sorted_users = sorted(active_users, key=lambda x: x[1], reverse=True)[:10]

        if not sorted_users:
            return await interaction.followup.send("Поки що порожньо.")

        bg_color = (43, 45, 49)
        text_color = (242, 243, 245)
        accent_color = (163, 196, 172)
        money_color = (220, 235, 225)
        line_color = (60, 63, 68) 
        
        width = 800
        height = 130 + (len(sorted_users) * 65)
        
        img = Image.new("RGB", (width, height), color=bg_color)
        draw = ImageDraw.Draw(img)

        try:
            font_title = ImageFont.truetype("arial.ttf", 40)
            font_text = ImageFont.truetype("arial.ttf", 32)
            font_rank = ImageFont.truetype("arial.ttf", 32)
        except IOError:
            font_title = ImageFont.load_default()
            font_text = ImageFont.load_default()
            font_rank = ImageFont.load_default()

        draw.line([(100, 85), (700, 85)], fill=accent_color, width=3)

        draw.text((width//2, 40), "Топ найбагатших гравців", fill=text_color, font=font_title, anchor="mm")

        y_offset = 110
        for i, (member, wealth) in enumerate(sorted_users, 1):
            draw.text((50, y_offset), f"#{i}", fill=accent_color, font=font_rank)
            
            try:
                avatar_bytes = await member.display_avatar.replace(size=64, format="png").read()
                avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                avatar_img = avatar_img.resize((40, 40), Image.Resampling.LANCZOS)
                
                mask = Image.new("L", (40, 40), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, 40, 40), fill=255)
                
                img.paste(avatar_img, (110, y_offset - 5), mask)
            except Exception as e:
                pass 
            
            name = member.display_name
            if len(name) > 16: 
                name = name[:14] + "..."
            draw.text((170, y_offset), name, fill=text_color, font=font_text)
            
            draw.text((width - 50, y_offset), f"{wealth} AC", fill=money_color, font=font_text, anchor="ra")
            
            draw.line([(50, y_offset + 50), (width - 50, y_offset + 50)], fill=line_color, width=1)
            
            y_offset += 65

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0) 

        file = discord.File(buffer, filename="leaderboard.png")
        
        embed = discord.Embed(color=0xa3c4ac)
        embed.set_image(url="attachment://leaderboard.png")
        
        await interaction.followup.send(embed=embed, file=file)

    @app_commands.command(name="sb_status", description="Статус СБ")
    @app_commands.guild_only()
    async def sb_status(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        bal = config.get("server_bank", 0)
        embed = discord.Embed(title="🏛️ Стан Казначейства", color=0xD4AF37)
        embed.add_field(name="Резерви", value=f"**{bal} AC**")
        embed.add_field(name="Статус", value=self.get_reserve_status(bal))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="sb_withdraw", description="[Адмін] Видати готівку з казни ")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def sb_withdraw(self, interaction: discord.Interaction, member: discord.User, amount: int):
        guild_id = interaction.guild.id
        c = load_guild_json(guild_id, ECONOMY_CONFIG)
        d = load_guild_json(guild_id, DATA_FILE)
        
        if amount > c.get("server_bank", 0): 
            return await interaction.response.send_message("У казні недостатньо коштів.", ephemeral=True)
        
        u = self.get_user(d, member.id)
        c["server_bank"] -= amount
        u["balance"] += amount
        
        save_guild_json(guild_id, ECONOMY_CONFIG, c)
        save_guild_json(guild_id, DATA_FILE, d)
        await interaction.response.send_message(f"🏛️ З казни видано **{amount} AC** для {member.mention}.")

    @app_commands.command(name="owner_refill_sb", description="[Власник] Поповнити СБ ")
    @app_commands.guild_only()
    async def owner_refill_sb(self, interaction: discord.Interaction, amount: int):
        if interaction.user.id != interaction.guild.owner_id: 
            return await interaction.response.send_message("Ця команда доступна лише власнику сервера.", ephemeral=True)
        
        guild_id = interaction.guild.id
        c = load_guild_json(guild_id, ECONOMY_CONFIG)
        c["server_bank"] = c.get("server_bank", 0) + amount
        save_guild_json(guild_id, ECONOMY_CONFIG, c)
        await interaction.response.send_message(f"Казну успішно поповнено на **{amount} AC**!")

async def setup(bot):
    await bot.add_cog(EconomyCog(bot))