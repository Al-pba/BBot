import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import os
import uuid
import random
from datetime import time as dt_time, timezone
from utils import load_guild_json, save_guild_json

DATA_FILE = "users.json"
MONOPOLY_FILE = "monopoly.json"
ECONOMY_CONFIG = "economy_config.json"

BASE_PRICES = {
    "офіс": 50000,
    "ферма": 45000,
    "завод": 50000,
    "склад": 30000,
    "сервер": 30000
}

PASSIVE_INCOME = {
    "завод": {"item": "materials", "amount": 10},
    "ферма": {"item": "crops", "amount": 10},
    "офіс": {"item": "data", "amount": 20},
    "склад": {"item": "none", "amount": 0},
    "сервер": {"item": "none", "amount": 0}
}

PROFESSIONS = {
    "завод": ["робітник", "менеджер"],
    "ферма": ["робітник", "агроном"],
    "офіс": ["робітник", "менеджер"],
    "склад": ["логіст", "охоронець", "менеджер"],
    "сервер": ["робітник"]
}

# ==========================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ==========================================

async def delete_company_data(guild: discord.Guild, owner_id: str, mono_data: dict):
    comp = mono_data["companies"].get(owner_id)
    if not comp: return
    
    channel_id = comp.get("channel_id")
    if channel_id:
        channel = guild.get_channel(channel_id)
        if channel:
            try: await channel.delete()
            except: pass
            
    prop_ids = list(comp["properties"].keys())
    offers_to_remove = [oid for oid, off in mono_data["rental_market"].items() if off["owner_id"] == owner_id]
    for oid in offers_to_remove: del mono_data["rental_market"][oid]
        
    rentals_to_remove = [rid for rid, rent in list(mono_data["active_rentals"].items()) if rent["owner_id"] == owner_id]
    for rid in rentals_to_remove:
        del mono_data["active_rentals"][rid]
        for uid, c in mono_data["companies"].items():
            for p in c["properties"].values():
                if p.get("connected_to") == f"rent_{rid}":
                    p["connected_to"] = None
                    
    rentals_where_renter = [rid for rid, rent in list(mono_data["active_rentals"].items()) if rent["renter_id"] == owner_id]
    for rid in rentals_where_renter:
        del mono_data["active_rentals"][rid]
        
    for uid, c in mono_data["companies"].items():
        if uid == owner_id: continue
        for p in c["properties"].values():
            if p.get("connected_to") in prop_ids:
                p["connected_to"] = None
                
    del mono_data["companies"][owner_id]
    save_guild_json(guild.id, MONOPOLY_FILE, mono_data)

def get_monopoly_data(guild_id: int):
    data = load_guild_json(guild_id, MONOPOLY_FILE)
    if not data:
        data = {
            "market_prices": BASE_PRICES.copy(),
            "used_market": [],
            "companies": {},
            "last_daily_tick": 0,
            "rental_market": {},
            "active_rentals": {} 
        }
    
    if "last_daily_tick" not in data: data["last_daily_tick"] = 0
    if "rental_market" not in data: data["rental_market"] = {}
    if "active_rentals" not in data: data["active_rentals"] = {}
    
    # === ГЕНЕРАЦІЯ ДЕРЖАВНОГО ПІДПРИЄМСТВА ===
    if "STATE_COMPANY" not in data["companies"]:
        state_props = {
            "state_warehouse": {"type": "склад", "name": "Державний Резерв", "level": 6, "durability": 100, "storage": {}, "connected_to": None, "hiring_mode": "open", "workers": {}, "salaries": {"логіст": 250, "охоронець": 300, "менеджер": 200}, "purchase_price": 50000},
            "state_factory": {"type": "завод", "name": "Державний Завод", "level": 3, "durability": 100, "storage": {}, "connected_to": "state_warehouse", "hiring_mode": "open", "workers": {}, "salaries": {"робітник": 15, "менеджер": 200}, "purchase_price": 50000},
            "state_farm": {"type": "ферма", "name": "Державні Угіддя", "level": 3, "durability": 100, "storage": {}, "connected_to": "state_warehouse", "hiring_mode": "open", "workers": {}, "salaries": {"робітник": 12, "агроном": 200}, "purchase_price": 45000},
            "state_office": {"type": "офіс", "name": "Державний Офіс", "level": 3, "durability": 100, "storage": {}, "connected_to": "state_warehouse", "hiring_mode": "open", "workers": {}, "salaries": {"робітник": 18, "менеджер": 250}, "purchase_price": 50000},
            "state_server_1": {"type": "сервер", "name": "Головний Держ-Сервер", "level": 3, "durability": 100, "storage": {}, "connected_to": "state_office", "hiring_mode": "open", "workers": {}, "salaries": {"робітник": 20}, "purchase_price": 30000},
            "state_server_2": {"type": "сервер", "name": "Резервний Держ-Сервер", "level": 2, "durability": 100, "storage": {}, "connected_to": "state_office", "hiring_mode": "open", "workers": {}, "salaries": {"робітник": 16}, "purchase_price": 30000}
        }
        data["companies"]["STATE_COMPANY"] = {
            "name": "🏛️ Державне Підприємство",
            "channel_id": None,
            "properties": state_props
        }
        save_guild_json(guild_id, MONOPOLY_FILE, data)
        
    return data

def calculate_capacity(level: int) -> int:
    cap = 100
    for _ in range(1, level):
        cap = int(cap * 1.10)
    return cap

def get_repair_cost(current_durability: int) -> int:
    if current_durability >= 100: return 0
    if current_durability >= 90: return 5
    if current_durability >= 60: return 15
    if current_durability >= 30: return 20
    return 30

def get_user_company(user_id: str, mono_data: dict):
    if user_id in mono_data["companies"]:
        return mono_data["companies"][user_id]
    
    for comp in mono_data["companies"].values():
        for prop in comp["properties"].values():
            if user_id in prop.get("workers", {}):
                return comp
    return None

def add_to_storage(company_id: str, mono_data: dict, start_pid: str, r_type: str, amount: int) -> int:
    company = mono_data["companies"][company_id]
    current_pid = start_pid
    remaining = amount
    visited = set() 
    
    while remaining > 0 and current_pid and current_pid not in visited:
        visited.add(current_pid)
        
        if current_pid.startswith("rent_"):
            real_pid = current_pid.replace("rent_", "")
            rent_data = mono_data["active_rentals"].get(real_pid)
            if not rent_data: break
            
            cap = rent_data["capacity"]
            current_total = sum(rent_data.get("storage", {}).values())
            space_left = max(0, cap - current_total)
            
            if space_left >= remaining:
                if "storage" not in rent_data: rent_data["storage"] = {}
                rent_data["storage"][r_type] = rent_data["storage"].get(r_type, 0) + remaining
                remaining = 0
            else:
                if space_left > 0:
                    if "storage" not in rent_data: rent_data["storage"] = {}
                    rent_data["storage"][r_type] = rent_data["storage"].get(r_type, 0) + space_left
                    remaining -= space_left
            break 
            
        else:
            prop = company["properties"].get(current_pid)
            if not prop: break
            
            cap = calculate_capacity(prop["level"])
            
            rented_cap = 0
            for offer in mono_data["rental_market"].values():
                if offer["prop_id"] == current_pid: rented_cap += offer["capacity"]
            for rent in mono_data["active_rentals"].values():
                if rent["prop_id"] == current_pid: rented_cap += rent["capacity"]
            
            cap = max(0, cap - rented_cap)
            
            current_total = sum(prop.get("storage", {}).values())
            space_left = max(0, cap - current_total)
            
            if space_left >= remaining:
                prop["storage"][r_type] = prop["storage"].get(r_type, 0) + remaining
                remaining = 0
            else:
                if space_left > 0:
                    prop["storage"][r_type] = prop["storage"].get(r_type, 0) + space_left
                    remaining -= space_left
                
                current_pid = prop.get("connected_to")
                
    return remaining

# ==========================================
# UI: ПЕРЕЙМЕНУВАННЯ, ПРОДАЖ ТА ПОКРАЩЕННЯ
# ==========================================

class TransferCompanyModal(discord.ui.Modal, title="Передача компанії"):
    name_input = discord.ui.TextInput(label="Введіть назву компанії для підтвердження", required=True)

    def __init__(self, owner_id: str, target_user: discord.User, mono_data: dict):
        super().__init__()
        self.owner_id = owner_id
        self.target_user = target_user
        self.mono_data = mono_data

    async def on_submit(self, interaction: discord.Interaction):
        target_id = str(self.target_user.id)
        comp = self.mono_data["companies"].get(self.owner_id)
        
        if not comp:
            return await interaction.response.send_message("У вас немає компанії.", ephemeral=True)
        
        if self.name_input.value.strip().lower() != comp["name"].strip().lower():
            return await interaction.response.send_message("Назва не збігається. Скасовано.", ephemeral=True)

        if target_id in self.mono_data["companies"]:
            return await interaction.response.send_message("У цільового гравця вже є інша компанія.", ephemeral=True)

        guild = interaction.guild

        for rent in self.mono_data["active_rentals"].values():
            if rent["owner_id"] == self.owner_id:
                rent["owner_id"] = target_id
            if rent["renter_id"] == self.owner_id:
                rent["renter_id"] = target_id

        for offer in self.mono_data["rental_market"].values():
            if offer["owner_id"] == self.owner_id:
                offer["owner_id"] = target_id

        self.mono_data["companies"][target_id] = self.mono_data["companies"].pop(self.owner_id)

        channel_id = comp.get("channel_id")
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                old_owner_member = guild.get_member(int(self.owner_id))
                if old_owner_member:
                    await channel.set_permissions(old_owner_member, overwrite=None)
                await channel.set_permissions(self.target_user, read_messages=True, send_messages=True)
                await channel.send(f"👑 Увага всім працівникам! Власник компанії змінився. Новий керівник: {self.target_user.mention}.")

        users_data = load_guild_json(guild.id, DATA_FILE)
        for uid, udata in users_data.items():
            job = udata.get("job", {})
            if job.get("company_id") == self.owner_id:
                udata["job"]["company_id"] = target_id
        save_guild_json(guild.id, DATA_FILE, users_data)

        save_guild_json(guild.id, MONOPOLY_FILE, self.mono_data)

        await interaction.response.send_message(f"Компанію **{comp['name']}** з усім майном, каналами та працівниками успішно передано гравцю {self.target_user.mention}!", ephemeral=False)

class DeleteCompanyModal(discord.ui.Modal, title="Видалення компанії"):
    name_input = discord.ui.TextInput(label="Введіть назву компанії для підтвердження", required=True)

    def __init__(self, owner_id: str, mono_data: dict):
        super().__init__()
        self.owner_id = owner_id
        self.mono_data = mono_data

    async def on_submit(self, interaction: discord.Interaction):
        comp = self.mono_data["companies"].get(self.owner_id)
        if not comp: return
        
        if self.name_input.value.strip().lower() != comp["name"].strip().lower():
            return await interaction.response.send_message("Назва не збігається. Скасовано.", ephemeral=True)
            
        await delete_company_data(interaction.guild, self.owner_id, self.mono_data)
        await interaction.response.send_message("Вашу компанію, приватний канал та все майно успішно видалено назавжди.", ephemeral=True)

class RenameCompanyModal(discord.ui.Modal, title="Зміна назви компанії"):
    name_input = discord.ui.TextInput(label="Нова назва", required=True, min_length=3, max_length=50)

    def __init__(self, owner_id: str, mono_data: dict):
        super().__init__()
        self.owner_id = owner_id
        self.mono_data = mono_data

    async def on_submit(self, interaction: discord.Interaction):
        self.mono_data["companies"][self.owner_id]["name"] = self.name_input.value
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
        await interaction.response.send_message(f"Назву компанії змінено на **{self.name_input.value}**.", ephemeral=True)

class RenamePropertyModal(discord.ui.Modal, title="Зміна назви майна"):
    name_input = discord.ui.TextInput(label="Нова назва", required=True, min_length=1, max_length=50)

    def __init__(self, owner_id: str, prop_id: str, mono_data: dict):
        super().__init__()
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.mono_data = mono_data

    async def on_submit(self, interaction: discord.Interaction):
        self.mono_data["companies"][self.owner_id]["properties"][self.prop_id]["name"] = self.name_input.value
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
        await interaction.response.send_message(f"Назву майна змінено на **{self.name_input.value}**.", ephemeral=True)

class SellPropertyModal(discord.ui.Modal, title="Підтвердження продажу"):
    name_input = discord.ui.TextInput(label="Введіть точну назву для підтвердження", required=True)

    def __init__(self, owner_id: str, prop_id: str, mono_data: dict):
        super().__init__()
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.mono_data = mono_data

    async def on_submit(self, interaction: discord.Interaction):
        prop = self.mono_data["companies"][self.owner_id]["properties"].get(self.prop_id)
        if not prop: return
        
        if self.name_input.value.strip().lower() != prop["name"].strip().lower():
            return await interaction.response.send_message("Помилка: Назва не збігається. Продаж скасовано.", ephemeral=True)
            
        prop = self.mono_data["companies"][self.owner_id]["properties"].pop(self.prop_id)
        
        used_item = {
            "id": self.prop_id,
            "type": prop["type"],
            "level": prop["level"],
            "name": f"Б/У {prop['type'].capitalize()}",
            "price": 40000,
            "durability": 50,
            "salaries": prop.get("salaries", {prof: 100 for prof in PROFESSIONS[prop["type"]]}),
            "purchase_price": prop.get("purchase_price", BASE_PRICES.get(prop["type"], 50000))
        }
        self.mono_data["used_market"].append(used_item)
        
        users_data = load_guild_json(interaction.guild.id, DATA_FILE)
        users_data[self.owner_id]["balance"] = users_data[self.owner_id].get("balance", 0) + 30000
        
        save_guild_json(interaction.guild.id, DATA_FILE, users_data)
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
        
        await interaction.response.send_message(f"Майно **{prop['name']}** успішно продано на Б/У ринок за 30,000 AC.", ephemeral=True)

class UpgradePropertyModal(discord.ui.Modal):
    name_input = discord.ui.TextInput(label="Введіть точну назву для підтвердження", required=True)

    def __init__(self, owner_id: str, prop_id: str, cost: int, mono_data: dict):
        super().__init__(title=f"Покращення: {cost} AC")
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.cost = cost
        self.mono_data = mono_data

    async def on_submit(self, interaction: discord.Interaction):
        prop = self.mono_data["companies"][self.owner_id]["properties"].get(self.prop_id)
        if not prop: return
        
        if self.name_input.value.strip().lower() != prop["name"].strip().lower():
            return await interaction.response.send_message("Помилка: Назва не збігається. Покращення скасовано.", ephemeral=True)
            
        guild_id = interaction.guild.id
        users_data = load_guild_json(guild_id, DATA_FILE)
        
        if users_data[self.owner_id].get("balance", 0) < self.cost:
            return await interaction.response.send_message(f"Недостатньо коштів. Потрібно {self.cost} AC.", ephemeral=True)
            
        users_data[self.owner_id]["balance"] -= self.cost
        
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        config["server_bank"] = config.get("server_bank", 0) + self.cost
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        
        prop["level"] += 1
        
        save_guild_json(guild_id, DATA_FILE, users_data)
        save_guild_json(guild_id, MONOPOLY_FILE, self.mono_data)
        
        await interaction.response.send_message(f"✅ Майно **{prop['name']}** успішно покращено до {prop['level']} рівня!", ephemeral=True)


# ==========================================
# UI: НАЛАШТУВАННЯ ЗАРПЛАТИ
# ==========================================

class SalarySetModal(discord.ui.Modal):
    def __init__(self, owner_id: str, prop_id: str, profession: str, mono_data: dict):
        super().__init__(title=f"Зарплата: {profession.capitalize()}")
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.profession = profession
        self.mono_data = mono_data

        self.salary_input = discord.ui.TextInput(
            label=f"ЗП для {profession} (AC)",
            placeholder="Наприклад: 500",
            required=True
        )
        self.add_item(self.salary_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.salary_input.value)
            if amount < 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("Введіть коректне додатне число.", ephemeral=True)

        prop = self.mono_data["companies"][self.owner_id]["properties"][self.prop_id]
        if "salaries" not in prop:
            prop["salaries"] = {prof: 100 for prof in PROFESSIONS[prop["type"]]}
        
        prop["salaries"][self.profession] = amount
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
        
        await interaction.response.send_message(f"ЗП для {self.profession} встановлено на `{amount} AC`.", ephemeral=True)

class ProfessionSelect(discord.ui.Select):
    def __init__(self, owner_id: str, prop_id: str, mono_data: dict):
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.mono_data = mono_data
        
        prop = mono_data["companies"][owner_id]["properties"][prop_id]
        profs = PROFESSIONS.get(prop["type"], [])
        salaries = prop.get("salaries", {})
        
        options = []
        for p in profs:
            current_salary = salaries.get(p, 100)
            options.append(discord.SelectOption(
                label=p.capitalize(),
                value=p,
                description=f"Поточна ЗП: {current_salary} AC"
            ))
        
        super().__init__(placeholder="Оберіть професію...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        profession = self.values[0]
        await interaction.response.send_modal(SalarySetModal(self.owner_id, self.prop_id, profession, self.mono_data))

class SalaryManageView(discord.ui.View):
    def __init__(self, owner_id: str, prop_id: str, mono_data: dict):
        super().__init__(timeout=120)
        self.add_item(ProfessionSelect(owner_id, prop_id, mono_data))

# ==========================================
# UI: СКЛАДНІ ОРЕНДИ ТА ЇХ СКАСУВАННЯ
# ==========================================

class RentOutModal(discord.ui.Modal, title="Здати склад в оренду"):
    def __init__(self, owner_id: str, prop_id: str, mono_data: dict):
        super().__init__()
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.mono_data = mono_data
        
        self.cap_input = discord.ui.TextInput(
            label="Кількість місця для оренди",
            placeholder="Наприклад: 50",
            required=True
        )
        self.price_input = discord.ui.TextInput(
            label="Ціна оренди за день (AC)",
            placeholder="Наприклад: 150",
            required=True
        )
        self.add_item(self.cap_input)
        self.add_item(self.price_input)
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            cap = int(self.cap_input.value)
            price = int(self.price_input.value)
            if cap <= 0 or price < 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("Введіть коректні числа.", ephemeral=True)
            
        prop = self.mono_data["companies"][self.owner_id]["properties"][self.prop_id]
        max_cap = calculate_capacity(prop["level"])
        
        rented_cap = 0
        for offer in self.mono_data["rental_market"].values():
            if offer["prop_id"] == self.prop_id: rented_cap += offer["capacity"]
        for rent in self.mono_data["active_rentals"].values():
            if rent["prop_id"] == self.prop_id: rented_cap += rent["capacity"]
            
        available_cap = max(0, max_cap - rented_cap)
        
        if cap > available_cap:
            return await interaction.response.send_message(f"Перевищено ліміт. Доступно для здачі: {available_cap} місць.", ephemeral=True)
            
        offer_id = str(uuid.uuid4())[:8]
        self.mono_data["rental_market"][offer_id] = {
            "owner_id": self.owner_id,
            "prop_id": self.prop_id,
            "capacity": cap,
            "price": price
        }
        
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
        await interaction.response.send_message(f"Створено нову пропозицію оренди: {cap} місць за {price} AC.", ephemeral=True)

class MutualRentCancelView(discord.ui.View):
    def __init__(self, rent_id: str, initiator_id: str, target_id: str, mono_data: dict):
        super().__init__(timeout=86400)
        self.rent_id = rent_id
        self.initiator_id = initiator_id
        self.target_id = target_id
        self.mono_data = mono_data

    @discord.ui.button(label="Підтвердити скасування", style=discord.ButtonStyle.danger)
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.target_id):
            return await interaction.response.send_message("Цей запит створено не для вас.", ephemeral=True)
            
        if self.rent_id in self.mono_data["active_rentals"]:
            del self.mono_data["active_rentals"][self.rent_id]
            
            for c_id, comp in self.mono_data["companies"].items():
                for p in comp["properties"].values():
                    if p.get("connected_to") == f"rent_{self.rent_id}":
                        p["connected_to"] = None
                        
            save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
            
            for child in self.children: child.disabled = True
            await interaction.response.edit_message(content=f"✅ <@{self.initiator_id}> та <@{self.target_id}> успішно розірвали договір оренди.", view=self)
            self.stop()
        else:
            await interaction.response.send_message("Оренда вже не активна.", ephemeral=True)

    @discord.ui.button(label="Відхилити", style=discord.ButtonStyle.secondary)
    async def decline_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.target_id):
            return await interaction.response.send_message("Цей запит створено не для вас.", ephemeral=True)
            
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"❌ <@{self.target_id}> відхилив пропозицію розірвати договір оренди.", view=self)
        self.stop()

class ManageRentalsSelect(discord.ui.Select):
    def __init__(self, owner_id: str, prop_id: str, mono_data: dict):
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.mono_data = mono_data
        options = []
        
        for offer_id, offer in mono_data["rental_market"].items():
            if offer["prop_id"] == prop_id and offer["owner_id"] == owner_id:
                options.append(discord.SelectOption(
                    label=f"Оффер: {offer['capacity']} місць",
                    value=f"offer_{offer_id}",
                    description=f"В очікуванні клієнта. Ціна: {offer['price']} AC"
                ))
                
        for rent_id, rent in mono_data["active_rentals"].items():
            if rent["prop_id"] == prop_id and rent["owner_id"] == owner_id:
                renter_name = "Орендар"
                if rent["renter_id"] in mono_data["companies"]:
                    renter_name = mono_data["companies"][rent["renter_id"]]["name"]
                    
                options.append(discord.SelectOption(
                    label=f"Активна оренда: {rent['capacity']} місць",
                    value=f"active_{rent_id}",
                    description=f"Орендує: {renter_name}. ЗП: {rent['price']} AC"
                ))
                
        if not options:
            options.append(discord.SelectOption(label="Немає активних пропозицій чи угод", value="none"))
            
        super().__init__(placeholder="Виберіть угоду/оффер для скасування...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none": return await interaction.response.defer()
        
        action_type, r_id = self.values[0].split("_", 1)
        
        if action_type == "offer":
            del self.mono_data["rental_market"][r_id]
            save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
            await interaction.response.send_message("Пропозицію оренди (оффер) скасовано.", ephemeral=True)
            
        elif action_type == "active":
            rent = self.mono_data["active_rentals"][r_id]
            target_id = rent["renter_id"]
            
            view = MutualRentCancelView(r_id, self.owner_id, target_id, self.mono_data)
            msg = f"🔔 <@{target_id}>, власник складу <@{self.owner_id}> пропонує розірвати договір оренди. Ви згодні?"
            
            await interaction.channel.send(content=msg, view=view)
            await interaction.response.send_message("Запит на скасування оренди успішно відправлено в чат.", ephemeral=True)

class ManageRentalsView(discord.ui.View):
    def __init__(self, owner_id: str, prop_id: str, mono_data: dict):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.mono_data = mono_data
        
        self.add_item(ManageRentalsSelect(owner_id, prop_id, mono_data))

    @discord.ui.button(label="Здати нову частину", style=discord.ButtonStyle.success)
    async def create_new_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RentOutModal(self.owner_id, self.prop_id, self.mono_data))

class TransferAcceptView(discord.ui.View):
    def __init__(self, sender_id, target_id, source_id, dest_id, is_source_rented, is_dest_rented, res_type, amount, mono_data):
        super().__init__(timeout=86400)
        self.sender_id, self.target_id = sender_id, target_id
        self.source_id, self.dest_id = source_id, dest_id
        self.is_source_rented, self.is_dest_rented = is_source_rented, is_dest_rented
        self.res_type, self.amount = res_type, amount

    @discord.ui.button(label="Прийняти ресурси", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.target_id): return await interaction.response.send_message("Це не для вас.", ephemeral=True)
            
        mono_data = get_monopoly_data(interaction.guild.id)
        source_data = mono_data["active_rentals"].get(self.source_id.replace("rent_", "")) if self.is_source_rented else mono_data["companies"].get(self.sender_id, {}).get("properties", {}).get(self.source_id)
        target_data = mono_data["active_rentals"].get(self.dest_id.replace("rent_", "")) if self.is_dest_rented else mono_data["companies"].get(self.target_id, {}).get("properties", {}).get(self.dest_id)
            
        if not source_data or not target_data: return await interaction.response.send_message("Один зі складів більше не існує.", ephemeral=True)
        if source_data.get("storage", {}).get(self.res_type, 0) < self.amount: return await interaction.response.send_message("У відправника вже немає цієї кількості.", ephemeral=True)
            
        cap = target_data.get("capacity") if self.is_dest_rented else calculate_capacity(target_data["level"])
        if not self.is_dest_rented:
            rented_out = sum(o["capacity"] for o in mono_data["rental_market"].values() if o["prop_id"] == self.dest_id) + sum(r["capacity"] for r in mono_data["active_rentals"].values() if r["prop_id"] == self.dest_id)
            cap = max(0, cap - rented_out)
            
        if sum(target_data.get("storage", {}).values()) + self.amount > cap:
            return await interaction.response.send_message("На вашому складі вже немає місця.", ephemeral=True)
            
        source_data["storage"][self.res_type] -= self.amount
        if "storage" not in target_data: target_data["storage"] = {}
        target_data["storage"][self.res_type] = target_data.get("storage", {}).get(self.res_type, 0) + self.amount
        
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, mono_data)
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content="Переказ успішно завершено.", view=self)
        self.stop()
        
    @discord.ui.button(label="Відхилити", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.target_id): return await interaction.response.send_message("Це не для вас.", ephemeral=True)
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content="Переказ відхилено.", view=self)
        self.stop()

class TransferResourceModal(discord.ui.Modal, title="Перенесення ресурсів"):
    target_id_input = discord.ui.TextInput(label="ID складу призначення", placeholder="Знайдіть ID в меню складу", required=True)
    res_type_input = discord.ui.TextInput(label="Тип (матеріали, врожай, дані)", required=True)
    amount_input = discord.ui.TextInput(label="Кількість", required=True)
    confirm_input = discord.ui.TextInput(label="Назва поточного складу (підтвердження)", required=True)

    def __init__(self, owner_id: str, prop_id: str, is_rented: bool, mono_data: dict):
        super().__init__()
        self.owner_id, self.prop_id, self.is_rented, self.mono_data = owner_id, prop_id, is_rented, mono_data

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value)
            if amount <= 0: raise ValueError
        except: return await interaction.response.send_message("Некоректна кількість.", ephemeral=True)
            
        res_type = self.res_type_input.value.strip().lower()
        if res_type not in ["матеріали", "врожай", "дані"]: return await interaction.response.send_message("Тип має бути: матеріали, врожай або дані.", ephemeral=True)
            
        source_data = self.mono_data["active_rentals"].get(self.prop_id.replace("rent_", "")) if self.is_rented else self.mono_data["companies"][self.owner_id]["properties"].get(self.prop_id)
        if not source_data: return
        source_name = "Орендований склад" if self.is_rented else source_data["name"]
        
        if self.confirm_input.value.strip().lower() != source_name.strip().lower():
            return await interaction.response.send_message("Назва підтвердження не збігається.", ephemeral=True)
            
        if source_data.get("storage", {}).get(res_type, 0) < amount: return await interaction.response.send_message("Недостатньо ресурсів на цьому складі.", ephemeral=True)

        target_id = self.target_id_input.value.strip()
        if target_id == self.prop_id: return await interaction.response.send_message("Не можна переказати на цей самий склад.", ephemeral=True)
            
        target_owner, target_name, target_is_rented = None, "", target_id.startswith("rent_")
        target_data = self.mono_data["active_rentals"].get(target_id.replace("rent_", "")) if target_is_rented else None
        
        if target_is_rented and target_data:
            target_owner, target_name = target_data["renter_id"], "Орендований склад"
        elif not target_is_rented:
            for uid, comp in self.mono_data["companies"].items():
                if target_id in comp["properties"]:
                    target_owner, target_data, target_name = uid, comp["properties"][target_id], comp["properties"][target_id]["name"]
                    break
                    
        if not target_data: return await interaction.response.send_message("Склад призначення не знайдено.", ephemeral=True)

        cap = target_data.get("capacity") if target_is_rented else calculate_capacity(target_data["level"])
        if not target_is_rented:
            rented_out = sum(o["capacity"] for o in self.mono_data["rental_market"].values() if o["prop_id"] == target_id) + sum(r["capacity"] for r in self.mono_data["active_rentals"].values() if r["prop_id"] == target_id)
            cap = max(0, cap - rented_out)
            
        if sum(target_data.get("storage", {}).values()) + amount > cap: return await interaction.response.send_message("На складі призначення недостатньо місця.", ephemeral=True)

        if target_owner == self.owner_id:
            source_data["storage"][res_type] -= amount
            if "storage" not in target_data: target_data["storage"] = {}
            target_data["storage"][res_type] = target_data.get("storage", {}).get(res_type, 0) + amount
            save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
            return await interaction.response.send_message("Ресурси успішно перенесено.", ephemeral=True)
        
        view = TransferAcceptView(self.owner_id, target_owner, self.prop_id, target_id, self.is_rented, target_is_rented, res_type, amount, self.mono_data)
        msg = f"🔔 <@{target_owner}>, гравець <@{self.owner_id}> хоче перенести `{amount}` одиниць `{res_type}` на ваш склад **{target_name}**. Згодні?"
        await interaction.channel.send(content=msg, view=view)
        await interaction.response.send_message("Запит на перенесення відправлено власнику.", ephemeral=True)

class RentalMarketSelect(discord.ui.Select):
    def __init__(self, mono_data: dict):
        self.mono_data = mono_data
        options = []
        for offer_id, offer in list(mono_data["rental_market"].items())[:25]:
            owner_comp = mono_data["companies"].get(offer["owner_id"], {}).get("name", "Невідома фірма")
            options.append(discord.SelectOption(
                label=f"Склад від {owner_comp}",
                value=offer_id,
                description=f"Місць: {offer['capacity']} | Ціна: {offer['price']} AC"
            ))
            
        if not options:
            options.append(discord.SelectOption(label="Пропозицій немає", value="none"))
            
        super().__init__(placeholder="Оберіть склад для оренди...", options=options)
        
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none": return await interaction.response.defer()
            
        offer_id = self.values[0]
        offer = self.mono_data["rental_market"][offer_id]
        
        user_id = str(interaction.user.id)
        guild_id = interaction.guild.id
        users_data = load_guild_json(guild_id, DATA_FILE)
        
        if user_id == offer["owner_id"]:
            return await interaction.response.send_message("Ви не можете орендувати власний склад.", ephemeral=True)
            
        if user_id not in self.mono_data["companies"]:
            return await interaction.response.send_message("Спочатку створіть власну компанію.", ephemeral=True)
            
        if users_data.get(user_id, {}).get("balance", 0) < offer["price"]:
            return await interaction.response.send_message(f"Недостатньо коштів для першого внеску. Потрібно {offer['price']} AC.", ephemeral=True)
            
        users_data[user_id]["balance"] -= offer["price"]
        owner_id = offer["owner_id"]
        if owner_id in users_data:
            users_data[owner_id]["balance"] = users_data.get(owner_id, {}).get("balance", 0) + offer["price"]
            
        rent_id = str(uuid.uuid4())[:8]
        self.mono_data["active_rentals"][rent_id] = {
            "owner_id": owner_id,
            "renter_id": user_id,
            "prop_id": offer["prop_id"],
            "capacity": offer["capacity"],
            "price": offer["price"],
            "storage": {}
        }
        del self.mono_data["rental_market"][offer_id]
        
        save_guild_json(guild_id, DATA_FILE, users_data)
        save_guild_json(guild_id, MONOPOLY_FILE, self.mono_data)
        
        await interaction.response.send_message("Склад успішно орендовано! Відтепер ви можете підключати до нього своє майно.", ephemeral=True)

class RentalMarketView(discord.ui.View):
    def __init__(self, mono_data: dict):
        super().__init__(timeout=120)
        self.add_item(RentalMarketSelect(mono_data))

# ==========================================
# UI: ПАНЕЛІ КЕРУВАННЯ
# ==========================================

class CompanyCreationModal(discord.ui.Modal, title="Реєстрація Компанії"):
    name_input = discord.ui.TextInput(label="Назва компанії", placeholder="Введіть назву фірми...", min_length=3, max_length=50)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user_id = str(interaction.user.id)
        
        users_data = load_guild_json(guild.id, DATA_FILE)
        if str(user_id) not in users_data or users_data[str(user_id)].get("balance", 0) < 20000:
            return await interaction.followup.send("Недостатньо коштів. Потрібно 20,000 AC.")

        mono_data = get_monopoly_data(guild.id)
        if user_id in mono_data["companies"]:
            return await interaction.followup.send("У вас вже є зареєстрована компанія.")

        users_data[user_id]["balance"] -= 20000
        
        config = load_guild_json(guild.id, ECONOMY_CONFIG)
        config["server_bank"] = config.get("server_bank", 0) + 20000
        save_guild_json(guild.id, ECONOMY_CONFIG, config)

        category = discord.utils.get(guild.categories, name="Фірми")
        if not category:
            category = await guild.create_category("Фірми")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        channel_name = self.name_input.value.lower().replace(" ", "-")
        channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)

        mono_data["companies"][user_id] = {
            "name": self.name_input.value,
            "channel_id": channel.id,
            "properties": {}
        }

        save_guild_json(guild.id, DATA_FILE, users_data)
        save_guild_json(guild.id, MONOPOLY_FILE, mono_data)

        await interaction.followup.send(f"Компанію створено. Ваш канал: {channel.mention}")

class PropertyConnectionSelect(discord.ui.Select):
    def __init__(self, owner_id: str, prop_id: str, mono_data: dict):
        self.owner_id = owner_id
        self.prop_id = prop_id
        self.mono_data = mono_data
        
        prop = mono_data["companies"][owner_id]["properties"][prop_id]
        p_type = prop["type"]
        
        options = [discord.SelectOption(label="Відключити", value="none")]
        
        for pid, pdata in mono_data["companies"][owner_id]["properties"].items():
            if pid == prop_id: continue
            
            if p_type in ["завод", "ферма"] and pdata["type"] == "склад":
                options.append(discord.SelectOption(label=f"{pdata['name']} (Склад)", value=pid))
            elif p_type == "офіс" and pdata["type"] in ["склад", "сервер"]:
                options.append(discord.SelectOption(label=f"{pdata['name']} ({pdata['type'].capitalize()})", value=pid))
            elif p_type == "сервер" and pdata["type"] == "склад":
                options.append(discord.SelectOption(label=f"{pdata['name']} (Склад)", value=pid))
            elif p_type == "склад" and pdata["type"] == "склад":
                options.append(discord.SelectOption(label=f"{pdata['name']} (Склад)", value=pid))
                
        for rent_id, rent_data in mono_data.get("active_rentals", {}).items():
            if rent_data["renter_id"] == owner_id and p_type in ["завод", "ферма", "офіс", "сервер", "склад"]:
                options.append(discord.SelectOption(
                    label=f"Орендований Склад ({rent_data['capacity']} місць)", 
                    value=f"rent_{rent_id}"
                ))

        if len(options) == 1:
            options[0].label = "Немає доступних об'єктів"
            
        super().__init__(placeholder="Оберіть об'єкт для підключення...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        target_id = self.values[0]
        prop = self.mono_data["companies"][self.owner_id]["properties"][self.prop_id]
        
        if target_id == "none":
            prop["connected_to"] = None
            msg = "Підключення розірвано."
        else:
            prop["connected_to"] = target_id
            msg = "Об'єкт підключено."
            
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
        await interaction.response.send_message(msg, ephemeral=True)

class PropertyManageView(discord.ui.View):
    def __init__(self, owner_id: str, prop_id: str, mono_data: dict, is_rented: bool = False):
        super().__init__(timeout=120)
        self.owner_id, self.prop_id, self.mono_data, self.is_rented = owner_id, prop_id, mono_data, is_rented
        
        if not is_rented:
            self.add_item(PropertyConnectionSelect(owner_id, prop_id, mono_data))
        
        prop = mono_data["active_rentals"][prop_id.replace("rent_", "")] if is_rented else mono_data["companies"][owner_id]["properties"][prop_id]
        p_type = "склад" if is_rented else prop["type"]
        
        if p_type == "склад":
            btn_trans = discord.ui.Button(label="Перенести ресурси", style=discord.ButtonStyle.success, row=4)
            btn_trans.callback = self.open_transfer_modal
            self.add_item(btn_trans)

        if not is_rented:
            if p_type == "склад":
                btn = discord.ui.Button(label="Управління орендою", style=discord.ButtonStyle.primary, row=3)
                btn.callback = self.open_rental_manager
                self.add_item(btn)

            btn_rep = discord.ui.Button(label="Відремонтувати", style=discord.ButtonStyle.success, row=1)
            btn_rep.callback = self.repair_btn
            self.add_item(btn_rep)

            btn_upg = discord.ui.Button(label="Покращити", style=discord.ButtonStyle.primary, row=1)
            btn_upg.callback = self.upgrade_btn
            self.add_item(btn_upg)

            btn_sell = discord.ui.Button(label="Продати на Б/У", style=discord.ButtonStyle.danger, row=1)
            btn_sell.callback = self.sell_btn
            self.add_item(btn_sell)

            btn_sal = discord.ui.Button(label="Налаштувати ЗП", style=discord.ButtonStyle.primary, row=2)
            btn_sal.callback = self.set_salary_btn
            self.add_item(btn_sal)

            btn_ren = discord.ui.Button(label="Перейменувати", style=discord.ButtonStyle.secondary, row=2)
            btn_ren.callback = self.rename_btn
            self.add_item(btn_ren)

            btn_hire = discord.ui.Button(label="Тип найму", style=discord.ButtonStyle.secondary, row=2)
            btn_hire.callback = self.toggle_hiring_btn
            self.add_item(btn_hire)

    async def open_transfer_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TransferResourceModal(self.owner_id, self.prop_id, self.is_rented, self.mono_data))

    async def open_rental_manager(self, interaction: discord.Interaction):
        view = ManageRentalsView(self.owner_id, self.prop_id, self.mono_data)
        await interaction.response.send_message("Керування пропозиціями та активною орендою для цього складу:", view=view, ephemeral=True)

    async def repair_btn(self, interaction: discord.Interaction):
        prop = self.mono_data["companies"][self.owner_id]["properties"][self.prop_id]
        if prop["durability"] >= 100: return await interaction.response.send_message("Майно не потребує ремонту.", ephemeral=True)
            
        cost = get_repair_cost(prop["durability"])
        resource_type = PASSIVE_INCOME[prop["type"]]["item"]
        
        if resource_type == "none":
            cost_ac = cost * 100
            guild_id = interaction.guild.id
            users_data = load_guild_json(guild_id, DATA_FILE)
            if users_data[self.owner_id].get("balance", 0) < cost_ac: return await interaction.response.send_message(f"Недостатньо коштів. Потрібно {cost_ac} AC.", ephemeral=True)
            users_data[self.owner_id]["balance"] -= cost_ac
            save_guild_json(guild_id, DATA_FILE, users_data)
            
            config = load_guild_json(guild_id, ECONOMY_CONFIG)
            config["server_bank"] = config.get("server_bank", 0) + cost_ac
            save_guild_json(guild_id, ECONOMY_CONFIG, config)
        else:
            if prop["storage"].get(resource_type, 0) < cost: return await interaction.response.send_message(f"Недостатньо сировини. Потрібно {cost} одиниць {resource_type}.", ephemeral=True)
            prop["storage"][resource_type] -= cost

        prop["durability"] = 100
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
        await interaction.response.send_message("Майно відремонтовано до 100%.", ephemeral=True)

    async def upgrade_btn(self, interaction: discord.Interaction):
        prop = self.mono_data["companies"][self.owner_id]["properties"][self.prop_id]
        if prop["durability"] == 0: return await interaction.response.send_message("Неможливо покращити зруйноване майно. Спочатку відремонтуйте його.", ephemeral=True)
            
        purchase_price = prop.get("purchase_price", BASE_PRICES.get(prop["type"], 50000))
        cost = int((purchase_price * 0.10) * (1.2 ** (prop["level"] - 1)))
        await interaction.response.send_modal(UpgradePropertyModal(self.owner_id, self.prop_id, cost, self.mono_data))

    async def sell_btn(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SellPropertyModal(self.owner_id, self.prop_id, self.mono_data))

    async def set_salary_btn(self, interaction: discord.Interaction):
        view = SalaryManageView(self.owner_id, self.prop_id, self.mono_data)
        await interaction.response.send_message("Оберіть професію для налаштування:", view=view, ephemeral=True)

    async def rename_btn(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RenamePropertyModal(self.owner_id, self.prop_id, self.mono_data))

    async def toggle_hiring_btn(self, interaction: discord.Interaction):
        prop = self.mono_data["companies"][self.owner_id]["properties"][self.prop_id]
        current = prop.get("hiring_mode", "closed")
        prop["hiring_mode"] = "open" if current == "closed" else "closed"
        save_guild_json(interaction.guild.id, MONOPOLY_FILE, self.mono_data)
        mode = "Відкритий" if prop["hiring_mode"] == "open" else "За заявками"
        await interaction.response.send_message(f"Режим найму змінено на: {mode}.", ephemeral=True)

class PropertiesDropdown(discord.ui.Select):
    def __init__(self, owner_id: str, mono_data: dict):
        self.owner_id = owner_id
        self.mono_data = mono_data
        
        options = []
        for pid, prop in list(mono_data["companies"][owner_id]["properties"].items())[:20]:
            state = "Зруйновано" if prop["durability"] == 0 else f"{prop['durability']}%"
            options.append(discord.SelectOption(label=f"{prop['name']} (Рівень {prop['level']})", value=pid, description=f"Тип: {prop['type'].capitalize()} | Міцність: {state}"))
            
        for rent_id, rent in mono_data.get("active_rentals", {}).items():
            if rent["renter_id"] == owner_id:
                options.append(discord.SelectOption(label=f"Орендований Склад", value=f"rent_{rent_id}", description=f"Місця: {rent['capacity']}"))
            
        if not options: options.append(discord.SelectOption(label="Немає майна", value="none"))
        super().__init__(placeholder="Оберіть нерухомість для керування...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none": return await interaction.response.defer()
            
        prop_id = self.values[0]
        is_rented = prop_id.startswith("rent_")
        
        if is_rented:
            rent = self.mono_data["active_rentals"][prop_id.replace("rent_", "")]
            embed = discord.Embed(title="Управління: Орендований склад", color=0x2b2d31)
            embed.add_field(name="Вартість оренди", value=f"{rent['price']} AC")
            cap = rent["capacity"]
            total_items = sum(rent.get("storage", {}).values())
            res_text = "\n".join([f"{k}: {v}" for k, v in rent.get("storage", {}).items() if v > 0])
            embed.add_field(name="Сховище", value=f"{res_text if res_text else 'Порожньо'}\n\nЗайнято: `{total_items}/{cap}`", inline=False)
        else:
            prop = self.mono_data["companies"][self.owner_id]["properties"][prop_id]
            embed = discord.Embed(title=f"Управління: {prop['name']}", color=0x2b2d31)
            embed.add_field(name="Тип", value=prop["type"].capitalize())
            embed.add_field(name="Рівень", value=f"{prop['level']} (Макс. працівників: {prop['level']})")
            embed.add_field(name="Міцність", value=f"{prop['durability']}%")
            
            cap = calculate_capacity(prop["level"])
            rented_cap = sum(o["capacity"] for o in self.mono_data["rental_market"].values() if o["prop_id"] == prop_id) + sum(r["capacity"] for r in self.mono_data["active_rentals"].values() if r["prop_id"] == prop_id)
            usable_cap = max(0, cap - rented_cap)
            total_items = sum(prop.get("storage", {}).values())
            
            res_text = "\n".join([f"{k}: {v}" for k, v in prop.get("storage", {}).items() if v > 0])
            cap_desc = f"{res_text if res_text else 'Порожньо'}\n\nЗайнято: `{total_items}/{usable_cap}`"
            if rented_cap > 0: cap_desc += f"\n*Виділено під оренду: {rented_cap}*"
            embed.add_field(name="Сховище", value=cap_desc, inline=False)
            
            conn_text = "Немає"
            if prop["connected_to"]:
                target_id = prop["connected_to"]
                if target_id.startswith("rent_"): conn_text = "Орендований склад"
                else: conn_text = self.mono_data["companies"][self.owner_id]["properties"].get(target_id, {}).get("name", "Невідомо")
            embed.add_field(name="Підключено до", value=conn_text)
            embed.add_field(name="Режим найму", value="Відкритий" if prop.get("hiring_mode") == "open" else "Закритий")

            salaries = prop.get("salaries", {})
            sal_text = "\n".join([f"{p.capitalize()}: {salaries.get(p, 100)} AC" for p in PROFESSIONS[prop["type"]]])
            embed.add_field(name="Зарплати", value=sal_text if sal_text else "Не налаштовано", inline=False)

        embed.set_footer(text=f"ID: {prop_id}")
        view = PropertyManageView(self.owner_id, prop_id, self.mono_data, is_rented)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class CompanyDashboardView(discord.ui.View):
    def __init__(self, owner_id: str, mono_data: dict):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.mono_data = mono_data
        self.add_item(PropertiesDropdown(owner_id, mono_data))
        
    @discord.ui.button(label="Змінити назву фірми", style=discord.ButtonStyle.secondary, row=1)
    async def rename_company_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RenameCompanyModal(self.owner_id, self.mono_data))

class MarketActionModal(discord.ui.Modal):
    def __init__(self, p_type: str, price: int, cog):
        super().__init__(title=f"Купівля: {p_type.capitalize()}")
        self.p_type = p_type
        self.price = price
        self.cog = cog
        
        self.name_input = discord.ui.TextInput(
            label="Назва нерухомості",
            placeholder="Наприклад: Головний Офіс",
            required=True
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        users_data = load_guild_json(guild_id, DATA_FILE)
        mono_data = get_monopoly_data(guild_id)
        
        if user_id not in mono_data["companies"]:
            return await interaction.response.send_message("Спочатку створіть компанію (/company_create).", ephemeral=True)
            
        if users_data[user_id].get("balance", 0) < self.price:
            return await interaction.response.send_message(f"Недостатньо коштів. Потрібно {self.price} AC.", ephemeral=True)
            
        users_data[user_id]["balance"] -= self.price
        
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        config["server_bank"] = config.get("server_bank", 0) + self.price
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        
        prop_id = str(uuid.uuid4())[:8]
        mono_data["companies"][user_id]["properties"][prop_id] = {
            "type": self.p_type,
            "name": self.name_input.value,
            "level": 1,
            "durability": 100,
            "storage": {},
            "connected_to": None,
            "hiring_mode": "closed",
            "is_rented": False,
            "workers": {},
            "salaries": {prof: 100 for prof in PROFESSIONS[self.p_type]},
            "purchase_price": self.price
        }
        
        current_price = mono_data["market_prices"][self.p_type]
        mono_data["market_prices"][self.p_type] = int(current_price * 1.10)
        
        save_guild_json(guild_id, DATA_FILE, users_data)
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        
        await interaction.response.send_message(f"Придбано **{self.name_input.value}** за {self.price} AC.", ephemeral=True)

class MarketBuySelect(discord.ui.Select):
    def __init__(self, mono_data: dict, cog):
        self.mono_data = mono_data
        self.cog = cog
        options = []
        for p_type, price in mono_data["market_prices"].items():
            options.append(discord.SelectOption(label=p_type.capitalize(), value=p_type, description=f"Ціна: {price} AC"))
            
        super().__init__(placeholder="Оберіть нову нерухомість для купівлі...", options=options)

    async def callback(self, interaction: discord.Interaction):
        p_type = self.values[0]
        price = self.mono_data["market_prices"][p_type]
        await interaction.response.send_modal(MarketActionModal(p_type, price, self.cog))

class UsedMarketBuySelect(discord.ui.Select):
    def __init__(self, mono_data: dict):
        self.mono_data = mono_data
        options = []
        for idx, item in enumerate(mono_data["used_market"][:25]):
            options.append(discord.SelectOption(
                label=f"{item['name']} (Рівень {item['level']})",
                value=str(idx),
                description=f"Тип: {item['type']} | Ціна: {item['price']} AC"
            ))
            
        if not options:
            options.append(discord.SelectOption(label="Ринок порожній", value="none"))
            
        super().__init__(placeholder="Оберіть Б/У нерухомість...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.defer()
            
        idx = int(self.values[0])
        item = self.mono_data["used_market"][idx]
        user_id = str(interaction.user.id)
        guild_id = interaction.guild.id
        
        users_data = load_guild_json(guild_id, DATA_FILE)
        if user_id not in self.mono_data["companies"]:
            return await interaction.response.send_message("Спочатку створіть компанію.", ephemeral=True)
            
        if users_data[user_id].get("balance", 0) < item["price"]:
            return await interaction.response.send_message("Недостатньо коштів.", ephemeral=True)
            
        users_data[user_id]["balance"] -= item["price"]
        
        config = load_guild_json(guild_id, ECONOMY_CONFIG)
        config["server_bank"] = config.get("server_bank", 0) + item["price"]
        save_guild_json(guild_id, ECONOMY_CONFIG, config)
        
        prop_id = str(uuid.uuid4())[:8]
        self.mono_data["companies"][user_id]["properties"][prop_id] = {
            "type": item["type"],
            "name": item["name"],
            "level": item["level"],
            "durability": item["durability"],
            "storage": {},
            "connected_to": None,
            "hiring_mode": "closed",
            "is_rented": False,
            "workers": {},
            "salaries": item.get("salaries", {prof: 100 for prof in PROFESSIONS[item["type"]]}),
            "purchase_price": item.get("purchase_price", item["price"])
        }
        
        self.mono_data["used_market"].pop(idx)
        
        save_guild_json(guild_id, DATA_FILE, users_data)
        save_guild_json(guild_id, MONOPOLY_FILE, self.mono_data)
        
        await interaction.response.send_message("Б/У нерухомість придбано.", ephemeral=True)

class MarketView(discord.ui.View):
    def __init__(self, mono_data: dict, cog):
        super().__init__(timeout=120)
        self.add_item(MarketBuySelect(mono_data, cog))
        self.add_item(UsedMarketBuySelect(mono_data))

# ==========================================
# ОСНОВНИЙ COG КЛАС
# ==========================================

class MonopolyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_monopoly_tick.start()
        self.market_fluctuation.start()
        self.restore_company_channels.start()

    def cog_unload(self):
        self.daily_monopoly_tick.cancel()
        self.market_fluctuation.cancel()
        self.restore_company_channels.cancel()

    @tasks.loop(hours=1)
    async def restore_company_channels(self):
        await self.bot.wait_until_ready()
        if not os.path.exists("server_data"): return

        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                guild = self.bot.get_guild(guild_id)
                if not guild: continue

                mono_data = get_monopoly_data(guild_id)
                updated = False

                for owner_id, comp in mono_data["companies"].items():
                    if owner_id == "STATE_COMPANY":
                        continue

                    channel_id = comp.get("channel_id")
                    channel = guild.get_channel(channel_id) if channel_id else None

                    if not channel:
                        category = discord.utils.get(guild.categories, name="Фірми")
                        if not category:
                            category = await guild.create_category("Фірми")

                        owner_member = guild.get_member(int(owner_id))
                        
                        overwrites = {
                            guild.default_role: discord.PermissionOverwrite(read_messages=False)
                        }
                        if owner_member:
                            overwrites[owner_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                        channel_name = comp["name"].lower().replace(" ", "-")
                        new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)
                        
                        comp["channel_id"] = new_channel.id
                        updated = True

                        workers = set()
                        for prop in comp["properties"].values():
                            for worker_id in prop.get("workers", {}).keys():
                                workers.add(worker_id)
                        
                        for worker_id in workers:
                            worker_member = guild.get_member(int(worker_id))
                            if worker_member:
                                await new_channel.set_permissions(worker_member, read_messages=True, send_messages=True)

                        await new_channel.send("🔄 Цей канал було автоматично відновлено системою. Всі доступи працівників збережено.")

                if updated:
                    save_guild_json(guild_id, MONOPOLY_FILE, mono_data)

            except Exception as e:
                pass

    @tasks.loop(time=dt_time(hour=0, minute=0, tzinfo=timezone.utc))
    async def daily_monopoly_tick(self):
        self._process_daily_tick()

    def _process_daily_tick(self):
        if not os.path.exists("server_data"): return
        current_time = int(time.time())
        
        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                data = get_monopoly_data(guild_id)
                users_data = load_guild_json(guild_id, DATA_FILE)
                
                if current_time - data.get("last_daily_tick", 0) < 86400:
                    continue
                    
                data["last_daily_tick"] = current_time
                updated = True
                
                for rent_id, rent_data in list(data["active_rentals"].items()):
                    renter_id = rent_data["renter_id"]
                    owner_id = rent_data["owner_id"]
                    price = rent_data["price"]
                    prop_id = rent_data["prop_id"]
                    
                    if rent_data.get("eviction_deadline", 0) > 0:
                        if current_time >= rent_data["eviction_deadline"]:
                            owner_prop = data["companies"][owner_id]["properties"][prop_id]
                            for r_type, r_amount in rent_data.get("storage", {}).items():
                                owner_prop["storage"][r_type] = owner_prop.get("storage", {}).get(r_type, 0) + r_amount
                            
                            del data["active_rentals"][rent_id]
                            if renter_id in data["companies"]:
                                for p in data["companies"][renter_id]["properties"].values():
                                    if p.get("connected_to") == f"rent_{rent_id}":
                                        p["connected_to"] = None
                        continue
                    
                    renter_balance = users_data.get(renter_id, {}).get("balance", 0)
                    if renter_balance >= price:
                        users_data[renter_id]["balance"] -= price
                        if owner_id in users_data:
                            users_data[owner_id]["balance"] = users_data.get(owner_id, {}).get("balance", 0) + price
                    else:
                        owner_prop = data["companies"][owner_id]["properties"][prop_id]
                        for r_type, r_amount in rent_data.get("storage", {}).items():
                            owner_prop["storage"][r_type] = owner_prop.get("storage", {}).get(r_type, 0) + r_amount
                            
                        del data["active_rentals"][rent_id]
                        if renter_id in data["companies"]:
                            for p in data["companies"][renter_id]["properties"].values():
                                if p.get("connected_to") == f"rent_{rent_id}":
                                    p["connected_to"] = None
                
                for uid, company in data["companies"].items():
                    for pid, prop in company["properties"].items():
                        if prop["durability"] > 0:
                            buffs = prop.get("buffs", {})
                            if buffs.get("security_expires", 0) > current_time:
                                pass 
                            else:
                                prop["durability"] = max(0, prop["durability"] - 10)
                                if prop["durability"] == 0:
                                    prop["level"] = 1
                            
                        if prop["durability"] > 0:
                            income_info = PASSIVE_INCOME.get(prop["type"])
                            if income_info and income_info["amount"] > 0:
                                r_type = income_info["item"]
                                amount = income_info["amount"]
                                
                                add_to_storage(uid, data, pid, r_type, amount)

                if updated:
                    save_guild_json(guild_id, MONOPOLY_FILE, data)
                    save_guild_json(guild_id, DATA_FILE, users_data)
            except Exception as e:
                print(f"Monopoly Daily Error: {e}")

    @tasks.loop(hours=6)
    async def market_fluctuation(self):
        if not os.path.exists("server_data"): return
        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                data = get_monopoly_data(guild_id)
                
                for p_type in data["market_prices"]:
                    trend = random.uniform(-0.05, 0.05)
                    base = BASE_PRICES[p_type]
                    current = data["market_prices"][p_type]
                    
                    if current > base * 1.5: trend -= 0.02
                    elif current < base * 0.5: trend += 0.02
                    
                    data["market_prices"][p_type] = int(current * (1 + trend))
                    
                save_guild_json(guild_id, MONOPOLY_FILE, data)
            except Exception as e:
                pass

    @daily_monopoly_tick.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()

    # --- КОМАНДИ ---

  
    @app_commands.command(name="company_create", description="Створити власну компанію (20,000 AC)")
    @app_commands.guild_only()
    async def company_create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CompanyCreationModal(self))

    @app_commands.command(name="company", description="Панель управління вашою компанією")
    @app_commands.guild_only()
    async def company_dashboard(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        mono_data = get_monopoly_data(guild_id)
        
        if user_id not in mono_data["companies"]:
            return await interaction.response.send_message("У вас немає компанії. Створіть її через /company_create.", ephemeral=True)
            
        comp = mono_data["companies"][user_id]
        embed = discord.Embed(title=f"Компанія: {comp['name']}", color=0x2b2d31)
        
        prop_list = []
        infra_list = []
        
        for pid, p in comp["properties"].items():
            status = "Зруйновано" if p["durability"] == 0 else f"{p['durability']}%"
            entry = f"**{p['name']}** ({p['type'].capitalize()}) | Рівень: {p['level']} | Міцність: {status}"
            
            if p["type"] in ["склад", "сервер"]:
                infra_list.append(entry)
            else:
                prop_list.append(entry)
                
        if prop_list:
            display_text = "\n".join(prop_list[:10])
            if len(prop_list) > 10: display_text += f"\n*...та ще {len(prop_list) - 10}*"
            embed.add_field(name="Виробництво та Офіси", value=display_text, inline=False)
        else:
            embed.add_field(name="Виробництво та Офіси", value="Немає", inline=False)

        if infra_list:
            display_text = "\n".join(infra_list[:10])
            if len(infra_list) > 10: display_text += f"\n*...та ще {len(infra_list) - 10}*"
            embed.add_field(name="Інфраструктура", value=display_text, inline=False)
        else:
            embed.add_field(name="Інфраструктура", value="Немає", inline=False)
            
        embed.add_field(name="Об'єктів нерухомості", value=str(len(comp["properties"])))
        workers_count = sum(len(p.get("workers", {})) for p in comp["properties"].values())
        embed.add_field(name="Загальний штат", value=str(workers_count))
        
        await interaction.response.send_message(embed=embed, view=CompanyDashboardView(user_id, mono_data), ephemeral=True)

    @app_commands.command(name="estate_market", description="Біржа нерухомості (Нова та Б/У)")
    @app_commands.guild_only()
    async def estate_market(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        
        embed = discord.Embed(title="Ринок Нерухомості", description="Ціни змінюються в залежності від ринку.", color=0x3498db)
        
        market_text = ""
        for p_type, price in mono_data["market_prices"].items():
            market_text += f"**{p_type.capitalize()}**: {price} AC\n"
        embed.add_field(name="Нові об'єкти", value=market_text, inline=False)
        
        used_count = len(mono_data["used_market"])
        embed.add_field(name="Б/У Ринок", value=f"Доступно об'єктів: {used_count}", inline=False)
        
        await interaction.response.send_message(embed=embed, view=MarketView(mono_data, self))

    @app_commands.command(name="rentals", description="Ринок оренди складів")
    @app_commands.guild_only()
    async def rentals(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        
        if not mono_data["rental_market"]:
            return await interaction.response.send_message("Наразі немає вільних складів для оренди.", ephemeral=True)
            
        embed = discord.Embed(title="Ринок оренди складів", color=0xf1c40f)
        await interaction.response.send_message(embed=embed, view=RentalMarketView(mono_data), ephemeral=True)

  
    @app_commands.command(name="transfer_property", description="Передати своє майно іншій фірмі")
    @app_commands.describe(target_user="Власник фірми, якій ви передаєте майно", prop_id="ID вашого майна (можна знайти в меню управління)")
    @app_commands.guild_only()
    async def transfer_property(self, interaction: discord.Interaction, target_user: discord.User, prop_id: str):
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        owner_id = str(interaction.user.id)
        target_id = str(target_user.id)
        
        if owner_id == target_id:
            return await interaction.response.send_message("Ви не можете передати майно самому собі.", ephemeral=True)
            
        if owner_id not in mono_data["companies"]:
            return await interaction.response.send_message("У вас немає компанії.", ephemeral=True)
            
        if target_id not in mono_data["companies"]:
            return await interaction.response.send_message("У цільового гравця немає зареєстрованої компанії.", ephemeral=True)
            
        prop = mono_data["companies"][owner_id]["properties"].get(prop_id)
        if not prop:
            return await interaction.response.send_message("Майно з таким ID не знайдено у вашій компанії.", ephemeral=True)
            
        offers_to_remove = [oid for oid, off in mono_data["rental_market"].items() if off["prop_id"] == prop_id]
        for oid in offers_to_remove:
            del mono_data["rental_market"][oid]
            
        rentals_to_remove = [rid for rid, rent in mono_data["active_rentals"].items() if rent["prop_id"] == prop_id]
        for rid in rentals_to_remove:
            del mono_data["active_rentals"][rid]
            for uid, comp in mono_data["companies"].items():
                for p in comp["properties"].values():
                    if p.get("connected_to") == f"rent_{rid}":
                        p["connected_to"] = None
                        
        for p in mono_data["companies"][owner_id]["properties"].values():
            if p.get("connected_to") == prop_id:
                p["connected_to"] = None
                
        prop["connected_to"] = None
        
        del mono_data["companies"][owner_id]["properties"][prop_id]
        mono_data["companies"][target_id]["properties"][prop_id] = prop
        
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        
        target_company_name = mono_data["companies"][target_id]["name"]
        await interaction.response.send_message(f"Ви успішно безкоштовно передали майно **{prop['name']}** компанії **{target_company_name}** ({target_user.mention}).", ephemeral=False)

   
    @app_commands.command(name="company_delete", description="Видалити власну компанію НАЗАВЖДИ")
    @app_commands.guild_only()
    async def company_delete(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        mono_data = get_monopoly_data(guild_id)
        
        if user_id not in mono_data["companies"]:
            return await interaction.response.send_message("У вас немає компанії.", ephemeral=True)
            
        await interaction.response.send_modal(DeleteCompanyModal(user_id, mono_data))

   
    @app_commands.command(name="warehouse", description="Переглянути вміст складів")
    @app_commands.guild_only()
    async def warehouse(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        mono_data = get_monopoly_data(guild_id)
        
        company = get_user_company(user_id, mono_data)
        
        if not company and not any(r["renter_id"] == user_id for r in mono_data.get("active_rentals", {}).values()):
            return await interaction.response.send_message("Ви не маєте доступу до жодного складу.", ephemeral=True)
            
        embed = discord.Embed(title="Ваші склади", color=0x2b2d31)
        
        if company:
            warehouses = {pid: p for pid, p in company["properties"].items() if p["type"] == "склад"}
            for pid, w in warehouses.items():
                cap = calculate_capacity(w["level"])
                
                rented_cap = 0
                for offer in mono_data.get("rental_market", {}).values():
                    if offer["prop_id"] == pid: rented_cap += offer["capacity"]
                for rent in mono_data.get("active_rentals", {}).values():
                    if rent["prop_id"] == pid: rented_cap += rent["capacity"]
                    
                usable_cap = max(0, cap - rented_cap)
                
                mats = w["storage"].get("materials", 0)
                crops = w["storage"].get("crops", 0)
                data_val = w["storage"].get("data", 0)
                total_items = mats + crops + data_val
                
                desc = (
                    f"Матеріали: `{mats}`\n"
                    f"Врожай: `{crops}`\n"
                    f"Дані: `{data_val}`\n\n"
                    f"Заповненість: `{total_items}/{usable_cap}`"
                )
                if rented_cap > 0:
                    desc += f"\n*Виділено під оренду: {rented_cap} місць*"
                    
                embed.add_field(name=f"{w['name']} (Рівень {w['level']})", value=desc, inline=False)
                
        for rent_id, rent_data in mono_data.get("active_rentals", {}).items():
            if rent_data["renter_id"] == user_id:
                cap = rent_data["capacity"]
                mats = rent_data.get("storage", {}).get("materials", 0)
                crops = rent_data.get("storage", {}).get("crops", 0)
                data_val = rent_data.get("storage", {}).get("data", 0)
                total_items = mats + crops + data_val
                
                owner_comp = mono_data["companies"].get(rent_data["owner_id"], {}).get("name", "Невідомо")
                
                desc = (
                    f"Матеріали: `{mats}`\n"
                    f"Врожай: `{crops}`\n"
                    f"Дані: `{data_val}`\n\n"
                    f"Заповненість: `{total_items}/{cap}`\n"
                    f"*Власник: {owner_comp}*"
                )
                embed.add_field(name="Орендований склад", value=desc, inline=False)
                
        if len(embed.fields) == 0:
            embed.description = "Порожньо."
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="company_transfer", description="Передати свою компанію іншому гравцю")
    @app_commands.guild_only()
    async def company_transfer(self, interaction: discord.Interaction, target_user: discord.User):
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        owner_id = str(interaction.user.id)
        target_id = str(target_user.id)

        if owner_id == target_id:
            return await interaction.response.send_message("Ви не можете передати компанію самому собі.", ephemeral=True)
        
        if owner_id not in mono_data["companies"]:
            return await interaction.response.send_message("У вас немає компанії.", ephemeral=True)

        if target_id in mono_data["companies"]:
            return await interaction.response.send_message("У цільового гравця вже є інша компанія.", ephemeral=True)

        await interaction.response.send_modal(TransferCompanyModal(owner_id, target_user, mono_data))

    @app_commands.command(name="force_daily", description="[АДМІН] Примусово викликати щоденне нарахування ресурсів")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def force_daily(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self._process_daily_tick()
        await interaction.followup.send("Щоденний цикл (знос + видобуток + оплата оренди) виконано примусово!")


    @app_commands.command(name="admin_remove_used", description="[АДМІН] Видалити майно з Б/У ринку")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def admin_remove_used(self, interaction: discord.Interaction, index: int):
        """
        Індекс лоту можна подивитись у меню /estate_market (перший лот це 0, другий 1 і т.д.)
        """
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        
        if index < 0 or index >= len(mono_data["used_market"]):
            return await interaction.response.send_message(f"Лот з індексом {index} не знайдено. Доступні індекси: 0 - {len(mono_data['used_market'])-1}", ephemeral=True)
            
        removed_item = mono_data["used_market"].pop(index)
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        
        await interaction.response.send_message(f"Лот **{removed_item['name']}** (Індекс: {index}) успішно видалено з Б/У ринку.", ephemeral=True)

    @app_commands.command(name="admin_storage", description="[АДМІН] Додати або забрати ресурси зі складу гравця")
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(res_type=[
        app_commands.Choice(name="Матеріали", value="materials"),
        app_commands.Choice(name="Врожай", value="crops"),
        app_commands.Choice(name="Дані", value="data")
    ])
    @app_commands.guild_only()
    async def admin_storage(self, interaction: discord.Interaction, owner: discord.User, prop_id: str, res_type: app_commands.Choice[str], amount: int):
        """
        amount може бути від'ємним, щоб забрати ресурси (наприклад -50)
        """
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        owner_id = str(owner.id)
        
        if owner_id not in mono_data["companies"]:
            return await interaction.response.send_message("У цього гравця немає компанії.", ephemeral=True)
            
        prop = mono_data["companies"][owner_id]["properties"].get(prop_id)
        if not prop:
            return await interaction.response.send_message("Майно з таким ID не знайдено у цього гравця.", ephemeral=True)
            
        if "storage" not in prop:
            prop["storage"] = {}
            
        current = prop["storage"].get(res_type.value, 0)
        new_amount = max(0, current + amount)
        prop["storage"][res_type.value] = new_amount
        
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        await interaction.response.send_message(f"Ресурси ({res_type.name}) на об'єкті **{prop['name']}** оновлено.\nБуло: `{current}`\nСтало: `{new_amount}`", ephemeral=True)


    @app_commands.command(name="admin_rename", description="[АДМІН] Примусово перейменувати компанію або майно")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def admin_rename(self, interaction: discord.Interaction, owner: discord.User, new_name: str, prop_id: str = None):
        """
        Якщо prop_id не вказано — перейменовується вся компанія.
        Якщо вказано ID майна — перейменовується лише це майно.
        """
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        owner_id = str(owner.id)
        
        if owner_id not in mono_data["companies"]:
            return await interaction.response.send_message("У цього гравця немає компанії.", ephemeral=True)
            
        if prop_id:
            prop = mono_data["companies"][owner_id]["properties"].get(prop_id)
            if not prop:
                return await interaction.response.send_message("❌ Майно з таким ID не знайдено.", ephemeral=True)
            old_name = prop["name"]
            prop["name"] = new_name
            save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
            await interaction.response.send_message(f"✅ Майно гравця {owner.mention} перейменовано з **{old_name}** на **{new_name}**.", ephemeral=True)
        else:
            comp = mono_data["companies"][owner_id]
            old_name = comp["name"]
            comp["name"] = new_name
            save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
            await interaction.response.send_message(f"✅ Компанію гравця {owner.mention} перейменовано з **{old_name}** на **{new_name}**.", ephemeral=True)


    @app_commands.command(name="admin_delete_company", description="[АДМІН] Примусово видалити чужу компанію")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def admin_delete_company(self, interaction: discord.Interaction, owner: discord.User):
        guild = interaction.guild
        mono_data = get_monopoly_data(guild.id)
        owner_id = str(owner.id)
        
        if owner_id not in mono_data["companies"]:
            return await interaction.response.send_message("❌ У цього гравця немає компанії.", ephemeral=True)
            
        comp_name = mono_data["companies"][owner_id]["name"]
        await delete_company_data(guild, owner_id, mono_data)
        await interaction.response.send_message(f"✅ Компанію **{comp_name}** гравця {owner.mention} та всі її зв'язки успішно видалено.", ephemeral=True)

    @app_commands.command(name="admin_transfer_property", description="[АДМІН] Примусово передати майно від одного гравця іншому")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def admin_transfer_property(self, interaction: discord.Interaction, current_owner: discord.User, target_owner: discord.User, prop_id: str):
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        owner_id = str(current_owner.id)
        target_id = str(target_owner.id)
        
        if owner_id not in mono_data["companies"]:
            return await interaction.response.send_message("У поточного власника немає компанії.", ephemeral=True)
            
        if target_id not in mono_data["companies"]:
            return await interaction.response.send_message("У цільового гравця немає компанії.", ephemeral=True)
            
        prop = mono_data["companies"][owner_id]["properties"].get(prop_id)
        if not prop:
            return await interaction.response.send_message("Майно з таким ID не знайдено у поточного власника.", ephemeral=True)
            
        offers_to_remove = [oid for oid, off in mono_data["rental_market"].items() if off["prop_id"] == prop_id]
        for oid in offers_to_remove: del mono_data["rental_market"][oid]
            
        rentals_to_remove = [rid for rid, rent in list(mono_data["active_rentals"].items()) if rent["prop_id"] == prop_id]
        for rid in rentals_to_remove:
            del mono_data["active_rentals"][rid]
            for uid, comp in mono_data["companies"].items():
                for p in comp["properties"].values():
                    if p.get("connected_to") == f"rent_{rid}":
                        p["connected_to"] = None
                        
        for p in mono_data["companies"][owner_id]["properties"].values():
            if p.get("connected_to") == prop_id:
                p["connected_to"] = None
                
        prop["connected_to"] = None
        
        del mono_data["companies"][owner_id]["properties"][prop_id]
        mono_data["companies"][target_id]["properties"][prop_id] = prop
        
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        await interaction.response.send_message(f"✅Майно **{prop['name']}** примусово передано компанії гравця {target_owner.mention}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(MonopolyCog(bot))