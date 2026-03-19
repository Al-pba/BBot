import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import random
import os
import uuid
from datetime import timezone
from utils import load_guild_json, save_guild_json

DATA_FILE = "users.json"
MONOPOLY_FILE = "monopoly.json"
ITEMS_TEMPLATES = "items_templates.json"
CRAFTS_FILE = "crafting_recipes.json"

RAW_NAMES = {
    "materials": "Деталі (Матеріали)",
    "crops": "Врожай",
    "data": "Дані"
}

# ==========================================
# ДОПОМІЖНІ ФУНКЦІЇ ДЛЯ СИРОВИНИ
# ==========================================

def get_user_raw_amount(mono_data: dict, user_id: str, res_type: str) -> int:
    """Рахує загальну кількість сировини на всіх складах користувача (власних і орендованих)"""
    total = 0
    if user_id in mono_data.get("companies", {}):
        for prop in mono_data["companies"][user_id].get("properties", {}).values():
            if prop["type"] == "склад":
                total += prop.get("storage", {}).get(res_type, 0)
    for rent in mono_data.get("active_rentals", {}).values():
        if rent["renter_id"] == user_id:
            total += rent.get("storage", {}).get(res_type, 0)
    return total

def deduct_user_raw_amount(mono_data: dict, user_id: str, res_type: str, amount: int):
    """Списує сировину зі складів користувача. Викликати ТІЛЬКИ після перевірки наявності!"""
    remaining = amount
    
    if user_id in mono_data.get("companies", {}):
        for prop in mono_data["companies"][user_id].get("properties", {}).values():
            if prop["type"] == "склад" and remaining > 0:
                available = prop.get("storage", {}).get(res_type, 0)
                if available > 0:
                    take = min(available, remaining)
                    prop["storage"][res_type] -= take
                    remaining -= take
                    
    if remaining > 0:
        for rent in mono_data.get("active_rentals", {}).values():
            if rent["renter_id"] == user_id and remaining > 0:
                available = rent.get("storage", {}).get(res_type, 0)
                if available > 0:
                    take = min(available, remaining)
                    rent["storage"][res_type] -= take
                    remaining -= take

def parse_items_string(s: str) -> dict:
    """Парсить рядок 'item1:2, item2:5' у словник {'item1': 2, 'item2': 5}"""
    res = {}
    if not s: return res
    for part in s.split(','):
        if ':' in part:
            k, v = part.split(':')
            try: res[k.strip().lower()] = int(v.strip())
            except: pass
    return res

# ==========================================
# UI: ЧЕРГА ТА ВІДМІНА КРАФТУ
# ==========================================

class CraftQueueView(discord.ui.View):
    def __init__(self, cog: commands.Cog, user_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id

    @discord.ui.button(label="Оновити статус", style=discord.ButtonStyle.primary, emoji="🔄", row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id: return await interaction.response.send_message("Не ваш профіль.", ephemeral=True)
        await self.cog.show_queue(interaction, self.user_id, edit=True)

    @discord.ui.select(placeholder="Скасувати крафт (Оберіть номер у черзі)...", min_values=1, max_values=1, options=[
        discord.SelectOption(label="Відмінити Слот 1", value="0"),
        discord.SelectOption(label="Відмінити Слот 2", value="1"),
        discord.SelectOption(label="Відмінити Слот 3", value="2"),
        discord.SelectOption(label="Відмінити Слот 4", value="3"),
        discord.SelectOption(label="Відмінити Слот 5", value="4"),
    ], row=0)
    async def cancel_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if str(interaction.user.id) != self.user_id: return await interaction.response.send_message("Це не ваша черга.", ephemeral=True)
        
        index = int(select.values[0])
        guild_id = interaction.guild.id
        
        data = load_guild_json(guild_id, DATA_FILE)
        mono_data = load_guild_json(guild_id, MONOPOLY_FILE)
        
        user_data = self.cog.get_user(data, self.user_id)
        queue = user_data["crafting_queue"]
        
        if index >= len(queue):
            return await interaction.response.send_message("У цьому слоті немає крафту.", ephemeral=True)
            
        canceled_item = queue.pop(index)
        costs = canceled_item.get("costs", {})
        
        # === ПОВЕРНЕННЯ РЕСУРСІВ ===
        if "money" in costs: user_data["balance"] += costs["money"]
        if "items" in costs: user_data["inventory"].extend(costs["items"])
        if "raw" in costs:
            for r_type, amt in costs["raw"].items():
                if amt > 0:
                    from cogs.monopoly import add_to_storage
                    add_to_storage(self.user_id, mono_data, list(mono_data["companies"][self.user_id]["properties"].keys())[0], r_type, amt)
        
        # === ПЕРЕРАХУНОК ЧАСУ ===
        current_time = int(time.time())
        for i, q_item in enumerate(queue):
            if i == 0:
                q_item["end_time"] = current_time + q_item["craft_time"]
            else:
                q_item["end_time"] = queue[i-1]["end_time"] + q_item["craft_time"]
                
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        
        await interaction.response.send_message(f"Крафт скасовано. Ресурси та гроші частково/повністю повернуто на ваші рахунки.", ephemeral=True)
        await self.cog.show_queue(interaction, self.user_id, edit=True)

# ==========================================
# UI: ВИБІР РЕЦЕПТУ ТА КРАФТ
# ==========================================

class CraftRecipeSelect(discord.ui.Select):
    def __init__(self, cog: commands.Cog, recipes: dict, items_db: dict):
        self.cog = cog
        self.recipes = recipes
        self.items_db = items_db
        
        options = []
        for r_id, r_data in list(recipes.items())[:25]:
            target_name = items_db.get(r_data["target_item"], {}).get("name", "Невідомий предмет")
            options.append(discord.SelectOption(
                label=target_name,
                value=r_id,
                description=f"⏱️ {r_data['time_secs']} сек | Шанс: {r_data['min_chance']}% - {r_data['max_chance']}%",
                emoji="⚒️"
            ))
            
        super().__init__(placeholder="Оберіть предмет для створення...", options=options)

    async def callback(self, interaction: discord.Interaction):
        recipe_id = self.values[0]
        recipe = self.recipes[recipe_id]
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        data = load_guild_json(guild_id, DATA_FILE)
        mono_data = load_guild_json(guild_id, MONOPOLY_FILE)
        
        user_data = self.cog.get_user(data, user_id)
        queue = user_data["crafting_queue"]
        
        if len(queue) >= 5:
            return await interaction.response.send_message("Ваша черга крафту заповнена (Максимум 5 предметів). Зачекайте завершення.", ephemeral=True)

        # === ПЕРЕВІРКА РЕСУРСІВ ===
        req_money = recipe.get("req_money", 0)
        req_raw = recipe.get("req_raw", {})
        req_items = recipe.get("req_items", {})

        if user_data["balance"] < req_money:
            return await interaction.response.send_message(f"Недостатньо AC. Потрібно: {req_money}", ephemeral=True)
            
        for r_type, amt in req_raw.items():
            if get_user_raw_amount(mono_data, user_id, r_type) < amt:
                return await interaction.response.send_message(f"Недостатньо сировини: **{RAW_NAMES.get(r_type, r_type)}**. Потрібно: {amt}", ephemeral=True)
                
        from collections import Counter
        inv_counts = Counter(user_data["inventory"])
        items_to_remove = []
        for i_id, amt in req_items.items():
            if inv_counts.get(i_id, 0) < amt:
                item_name = self.items_db.get(i_id, {}).get("name", i_id)
                return await interaction.response.send_message(f"Недостатньо предметів: **{item_name}**. Потрібно: {amt}", ephemeral=True)
            items_to_remove.extend([i_id] * amt)

        # === СПИСАННЯ РЕСУРСІВ ===
        user_data["balance"] -= req_money
        
        for r_type, amt in req_raw.items():
            deduct_user_raw_amount(mono_data, user_id, r_type, amt)
            
        for item in items_to_remove:
            user_data["inventory"].remove(item)

        # === ДОДАВАННЯ В ЧЕРГУ ===
        current_time = int(time.time())
        if not queue:
            end_time = current_time + recipe["time_secs"]
        else:
            end_time = queue[-1]["end_time"] + recipe["time_secs"]
            
        queue_item = {
            "id": str(uuid.uuid4())[:8],
            "recipe_id": recipe_id,
            "target_item": recipe["target_item"],
            "craft_time": recipe["time_secs"],
            "end_time": end_time,
            "costs": {
                "money": req_money,
                "raw": req_raw,
                "items": items_to_remove
            }
        }
        queue.append(queue_item)
        
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        
        target_name = self.items_db.get(recipe["target_item"], {}).get("name", "Предмет")
        await interaction.response.send_message(f"Виготовлення **{target_name}** успішно додано до черги! Завершиться <t:{end_time}:R>.", ephemeral=True)

class CraftMenuView(discord.ui.View):
    def __init__(self, cog, recipes: dict, items_db: dict):
        super().__init__(timeout=120)
        self.add_item(CraftRecipeSelect(cog, recipes, items_db))


# ==========================================
# ОСНОВНИЙ КОГ: КРАФТ
# ==========================================

class CraftsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.process_crafting_queue.start()

    def get_user(self, data, uid):
        uid = str(uid)
        if uid not in data: data[uid] = {}
        data[uid].setdefault("balance", 0)
        data[uid].setdefault("inventory", [])
        data[uid].setdefault("level", 1)
        data[uid].setdefault("crafting_queue", [])
        return data[uid]

    @tasks.loop(seconds=15)
    async def process_crafting_queue(self):
        """Фонова задача, яка перевіряє чергу і видає предмети"""
        if not os.path.exists("server_data"): return
        current_time = int(time.time())
        
        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                data = load_guild_json(guild_id, DATA_FILE)
                recipes = load_guild_json(guild_id, CRAFTS_FILE)
                items_db = load_guild_json(guild_id, ITEMS_TEMPLATES)
                updated = False
                
                for uid, user_data in data.items():
                    queue = user_data.get("crafting_queue", [])
                    if not queue: continue
                    
                    while queue and queue[0]["end_time"] <= current_time:
                        finished_item = queue.pop(0)
                        recipe = recipes.get(finished_item["recipe_id"])
                        updated = True
                        
                        target_name = items_db.get(finished_item["target_item"], {}).get("name", "Невідомий предмет")
                        
                        if not recipe:
                            user_data["inventory"].append(finished_item["target_item"])
                            continue
                            
                        # === РОЗРАХУНОК ШАНСІВ ===
                        user_lvl = user_data.get("level", 1)
                        chance = min(recipe["min_chance"] + user_lvl, recipe["max_chance"])
                        
                        crafted_count = 0
                        
                        if chance >= 100:
                            crafted_count += 1
                            chance -= 100
                            
                        if chance > 0 and random.randint(1, 100) <= chance:
                            crafted_count += 1
                            
                        # === РЕЗУЛЬТАТ ===
                        guild = self.bot.get_guild(guild_id)
                        member = guild.get_member(int(uid)) if guild else None
                        
                        if crafted_count > 0:
                            user_data["inventory"].extend([finished_item["target_item"]] * crafted_count)
                            if member:
                                try: await member.send(f"Ваш крафт завершено! Ви отримали: **{target_name}** (x{crafted_count}).")
                                except: pass
                        else:
                            if member:
                                try: await member.send(f"Крафт не вдався... Ваші ресурси згоріли під час спроби зробити **{target_name}**.")
                                except: pass

                if updated:
                    save_guild_json(guild_id, DATA_FILE, data)
            except Exception as e:
                print(f"Crafting Queue Error: {e}")

    @process_crafting_queue.before_loop
    async def before_craft_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="crafts", description="Переглянути доступні рецепти та почати крафт")
    @app_commands.guild_only()
    async def crafts(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        recipes = load_guild_json(guild_id, CRAFTS_FILE)
        items_db = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        if not recipes:
            return await interaction.response.send_message("На сервері ще немає доступних рецептів для крафту.", ephemeral=True)
            
        embed = discord.Embed(title="⚒️ Майстерня: Доступні рецепти", description="Використовуйте меню нижче, щоб додати крафт у чергу.", color=0xe67e22)
        
        for r_id, r in recipes.items():
            target_name = items_db.get(r["target_item"], {}).get("name", r["target_item"])
            
            reqs = []
            if r.get("req_money", 0) > 0: reqs.append(f"💰 `{r['req_money']} AC`")
            for rt, amt in r.get("req_raw", {}).items():
                if amt > 0: reqs.append(f"📦 {RAW_NAMES.get(rt, rt)}: `{amt}`")
            for it, amt in r.get("req_items", {}).items():
                if amt > 0:
                    it_name = items_db.get(it, {}).get("name", it)
                    reqs.append(f"🎒 {it_name}: `{amt}`")
                    
            req_str = "\n".join(reqs) if reqs else "Безкоштовно"
            
            embed.add_field(
                name=f"🔨 {target_name}",
                value=f"**Час:** {r['time_secs']} сек.\n**Шанс успіху:** {r['min_chance']}% (Макс: {r['max_chance']}%)\n**Вимоги:**\n{req_str}",
                inline=True
            )
            
        await interaction.response.send_message(embed=embed, view=CraftMenuView(self, recipes, items_db), ephemeral=True)

    async def show_queue(self, interaction: discord.Interaction, user_id: str, edit: bool = False):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        items_db = load_guild_json(guild_id, ITEMS_TEMPLATES)
        user_data = self.get_user(data, user_id)
        queue = user_data["crafting_queue"]
        
        embed = discord.Embed(title="⏱️ Ваша черга крафту", color=0x3498db)
        
        if not queue:
            embed.description = "Черга порожня. Використовуйте `/crafts`, щоб почати виготовлення."
            if edit: await interaction.message.edit(embed=embed, view=None)
            else: await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        embed.description = f"Зайнято слотів: **{len(queue)}/5**\n*Крафти виконуються послідовно.*"
        
        for i, q in enumerate(queue):
            t_name = items_db.get(q["target_item"], {}).get("name", "Предмет")
            embed.add_field(
                name=f"Слот {i+1}: {t_name}",
                value=f"Завершення: <t:{q['end_time']}:R>",
                inline=False
            )
            
        view = CraftQueueView(self, user_id)
        if edit:
            if interaction.response.is_done(): await interaction.edit_original_response(embed=embed, view=view)
            else: await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="craft_queue", description="Переглянути та керувати вашою чергою крафту")
    @app_commands.guild_only()
    async def craft_queue(self, interaction: discord.Interaction):
        await self.show_queue(interaction, str(interaction.user.id))

    @app_commands.command(name="admin_craft_add", description="[АДМІН] Створити новий рецепт")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        target_item="ID предмета з /items_list, який буде створено",
        time_secs="Час на крафт у секундах",
        req_items="ID необхідних предметів (напр: wood:2,iron:1)"
    )
    async def admin_craft_add(self, interaction: discord.Interaction, 
                              target_item: str, time_secs: int, min_chance: int, max_chance: int,
                              req_money: int = 0, req_materials: int = 0, req_crops: int = 0, req_data: int = 0,
                              req_items: str = ""):
                              
        guild_id = interaction.guild.id
        recipes = load_guild_json(guild_id, CRAFTS_FILE)
        items_db = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        target_item = target_item.lower().strip().replace(" ", "_")
        if target_item not in items_db:
            return await interaction.response.send_message(f"Предмет `{target_item}` не існує в базі. Створіть його через /item_create.", ephemeral=True)
            
        recipe_id = str(uuid.uuid4())[:6]
        parsed_items = parse_items_string(req_items)
        
        recipes[recipe_id] = {
            "target_item": target_item,
            "time_secs": time_secs,
            "min_chance": min_chance,
            "max_chance": max_chance,
            "req_money": req_money,
            "req_raw": {
                "materials": req_materials,
                "crops": req_crops,
                "data": req_data
            },
            "req_items": parsed_items
        }
        
        save_guild_json(guild_id, CRAFTS_FILE, recipes)
        await interaction.response.send_message(f"Рецепт успішно створено! ID рецепту: `{recipe_id}`", ephemeral=True)

    @app_commands.command(name="admin_craft_remove", description="[АДМІН] Видалити рецепт за його ID")
    @app_commands.default_permissions(administrator=True)
    async def admin_craft_remove(self, interaction: discord.Interaction, recipe_id: str):
        guild_id = interaction.guild.id
        recipes = load_guild_json(guild_id, CRAFTS_FILE)
        
        if recipe_id not in recipes:
            return await interaction.response.send_message("Рецепт з таким ID не знайдено.", ephemeral=True)
            
        del recipes[recipe_id]
        save_guild_json(guild_id, CRAFTS_FILE, recipes)
        await interaction.response.send_message(f"Рецепт `{recipe_id}` видалено.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(CraftsCog(bot))