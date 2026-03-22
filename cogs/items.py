import discord
from discord.ext import commands
from discord import app_commands
from collections import Counter
from utils import load_guild_json, save_guild_json
import asyncio

DATA_FILE = "users.json"
ITEMS_TEMPLATES = "items_templates.json"

class ItemsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_user(self, data, uid):
        uid = str(uid)
        if uid not in data:
            data[uid] = {}
        
        data[uid].setdefault("balance", 0)
        data[uid].setdefault("level", 1)
        data[uid].setdefault("inventory", [])
        data[uid].setdefault("stats", {
            "strength": 1, "agility": 1, "physique": 1, 
            "intelligence": 1, "wisdom": 1, "charisma": 1
        })
        return data[uid]

    def format_id(self, item_id: str) -> str:
        return item_id.lower().strip().replace(" ", "_")

    def get_item_sort_key(self, item_info):
        rarity_ranks = {
            "🟡 Legendary": 1,
            "🟣 Epic": 2,
            "🔵 Rare": 3,
            "⚪ Common": 4
        }
        rarity = item_info.get('rarity', '⚪ Common')
        name = item_info.get('name', 'Unknown')
        rank = rarity_ranks.get(rarity, 5)
        return (rank, name.lower())

    async def remove_role_later(self, member: discord.User, role: discord.Role, minutes: int):
        await asyncio.sleep(minutes * 60)
        try:
            if member.guild.get_member(member.id) and role in member.roles:
                await member.remove_roles(role)
                print(f"[Log] Тимчасову роль {role.name} знято з {member.display_name}")
        except Exception as e:
            print(f"[Error] Не вдалося зняти роль: {e}")

    @app_commands.command(name="items_list", description="Переглянути всі існуючі предмети")
    @app_commands.guild_only()
    async def items_list(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        if not templates:
            return await interaction.response.send_message("Дефіцит речей.", ephemeral=True)

        sorted_items = sorted(templates.items(), key=lambda x: self.get_item_sort_key(x[1]))

        embed = discord.Embed(title="Реєстр предметів сервера", color=0x95a5a6)
        
        lines = []
        for i_id, info in sorted_items:
            lines.append(f"{info['rarity']} **{info['name']}** `[{i_id}]`")
        
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inventory", description="Переглянути свій рюкзак")
    @app_commands.guild_only()
    async def inventory(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        user = self.get_user(data, interaction.user.id)
        user_inv = user.get("inventory", [])
        
        if not user_inv:
            return await interaction.response.send_message("Ваш рюкзак порожній.", ephemeral=True)

        counts = Counter(user_inv)
        
        sorted_inv = sorted(counts.items(), key=lambda x: self.get_item_sort_key(templates.get(x[0], {})))

        embed = discord.Embed(title=f"Інвентар {interaction.user.display_name}", color=0x3498db)
        
        lines = []
        for i_id, count in sorted_inv:
            item = templates.get(i_id, {"name": "Unknown", "rarity": "❓"})
            lines.append(f"{item['rarity']} **{item['name']}** `[{i_id}]` x{count}")
        
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gift", description="Подарувати предмет іншому гравцю")
    @app_commands.guild_only()
    async def gift(self, interaction: discord.Interaction, member: discord.User, item_id: str, amount: int = 1):
        if amount <= 0 or member.id == interaction.user.id or member.bot:
            return await interaction.response.send_message("Некоректна кількість або ціль.", ephemeral=True)

        guild_id = interaction.guild.id
        processed_id = self.format_id(item_id)
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        if processed_id not in templates:
            return await interaction.response.send_message("Такого предмета не існує.", ephemeral=True)

        data = load_guild_json(guild_id, DATA_FILE)
        sender = self.get_user(data, interaction.user.id)
        receiver = self.get_user(data, member.id)

        if sender["inventory"].count(processed_id) < amount:
            return await interaction.response.send_message(f"У вас недостатньо `{processed_id}` x{amount}.", ephemeral=True)

        for _ in range(amount):
            sender["inventory"].remove(processed_id)
            receiver["inventory"].append(processed_id)

        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"🎁 {interaction.user.mention} подарував {member.mention} **{templates[processed_id]['name']}** (x{amount})!")

    @app_commands.command(name="use", description="Використати предмет")
    @app_commands.guild_only()
    async def use(self, interaction: discord.Interaction, item_id: str):
        guild_id = interaction.guild.id
        processed_id = self.format_id(item_id)
        data = load_guild_json(guild_id, DATA_FILE)
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        user = self.get_user(data, interaction.user.id)
        
        if processed_id not in user["inventory"]:
            return await interaction.response.send_message("У вас немає цього предмета!", ephemeral=True)

        item = templates.get(processed_id)
        if not item: 
            return await interaction.response.send_message("Шаблон цього предмета не знайдено.")

        log = []
        
        if item.get("money"):
            user["balance"] += item["money"]
            log.append(f"💰 +{item['money']} AC")
        
        if item.get("xp"):
            user["level"] += item["xp"]
            log.append(f"✨ +{item['xp']} LVL")

        if item.get("stat_name") and item.get("stat_value"):
            s_name = item["stat_name"]
            user["stats"][s_name] = user["stats"].get(s_name, 1) + item["stat_value"]
            log.append(f"📊 {s_name.capitalize()}: +{item['stat_value']}")

        if item.get("role_id"):
            role = interaction.guild.get_role(item["role_id"])
            if role:
                try:
                    await interaction.user.add_roles(role)
                    duration = item.get("role_duration", 0)
                    
                    if duration > 0:
                        log.append(f"Отримано роль: **{role.name}** на {duration} хв.")
                        asyncio.create_task(self.remove_role_later(interaction.user, role, duration))
                    else:
                        log.append(f"Отримано роль: **{role.name}**")
                except:
                    log.append("⚠️ Помилка видачі ролі (перевірте ієрархію бота)")

        user["inventory"].remove(processed_id)
        save_guild_json(guild_id, DATA_FILE, data)
        
        emb = discord.Embed(
            title=f"Використано: {item['name']}", 
            description="\n".join(log) if log else "Ефектів немає.", 
            color=0xf1c40f
        )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="item_create", description="[Адмін] Створити шаблон предмета")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.choices(rarity=[
        app_commands.Choice(name="Common (⚪)", value="⚪ Common"),
        app_commands.Choice(name="Rare (🔵)", value="🔵 Rare"),
        app_commands.Choice(name="Epic (🟣)", value="🟣 Epic"),
        app_commands.Choice(name="Legendary (🟡)", value="🟡 Legendary")
    ], stat_to_boost=[
        app_commands.Choice(name="Сила (Strength)", value="strength"),
        app_commands.Choice(name="Спритність (Agility)", value="agility"),
        app_commands.Choice(name="Тілобудова (Physique)", value="physique"),
        app_commands.Choice(name="Інтелект (Intelligence)", value="intelligence"),
        app_commands.Choice(name="Мудрість (Wisdom)", value="wisdom"),
        app_commands.Choice(name="Харизма (Charisma)", value="charisma")
    ])
    async def item_create(self, interaction: discord.Interaction, 
                          item_id: str, 
                          name: str, 
                          rarity: app_commands.Choice[str],
                          give_money: int = 0,
                          give_xp_levels: int = 0,
                          give_role: discord.Role = None,
                          role_duration: int = 0,
                          stat_to_boost: app_commands.Choice[str] = None,
                          stat_value: int = 0):
        guild_id = interaction.guild.id
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        processed_id = self.format_id(item_id)
        
        templates[processed_id] = {
            "name": name,
            "rarity": rarity.value,
            "money": give_money,
            "xp": give_xp_levels,
            "role_id": give_role.id if give_role else None,
            "role_duration": role_duration,
            "stat_name": stat_to_boost.value if stat_to_boost else None,
            "stat_value": stat_value
        }
        
        save_guild_json(guild_id, ITEMS_TEMPLATES, templates)
        
        emb = discord.Embed(title="Предмет створено", color=0x2ecc71)
        emb.add_field(name="Назва", value=f"{rarity.value} **{name}**", inline=True)
        emb.add_field(name="ID", value=f"`{processed_id}`", inline=True)
        
        effects = []
        if give_money: effects.append(f"💰 +{give_money} AC")
        if give_xp_levels: effects.append(f"✨ +{give_xp_levels} LVL")
        if give_role: 
            dur_text = f"(на {role_duration} хв.)" if role_duration > 0 else "(назавжди)"
            effects.append(f"Роль: {give_role.mention} {dur_text}")
        if stat_to_boost: effects.append(f"📊 {stat_to_boost.name}: +{stat_value}")
        
        emb.add_field(name="Ефекти", value="\n".join(effects) if effects else "Декор", inline=False)
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="item_delete", description="[Адмін] Видалити шаблон предмета з бази")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def item_delete(self, interaction: discord.Interaction, item_id: str):
        guild_id = interaction.guild.id
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        processed_id = self.format_id(item_id)

        if processed_id not in templates:
            return await interaction.response.send_message(
                f"Предмет з ID `{processed_id}` не знайдено в базі!", 
                ephemeral=True
            )

        item_name = templates[processed_id].get('name', 'Невідомий предмет')
        
        del templates[processed_id]
        
        save_guild_json(guild_id, ITEMS_TEMPLATES, templates)
        
        emb = discord.Embed(
            title="Предмет видалено", 
            description=f"Шаблон предмета **{item_name}** (`{processed_id}`) повністю видалено з бази сервера.",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="item_give", description="[Адмін] Видати предмет гравцю")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def item_give(self, interaction: discord.Interaction, member: discord.User, item_id: str):
        guild_id = interaction.guild.id
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        processed_id = self.format_id(item_id)
        
        if processed_id not in templates:
            return await interaction.response.send_message(f"Предмет з ID `{processed_id}` не знайдено!", ephemeral=True)

        data = load_guild_json(guild_id, DATA_FILE)
        user = self.get_user(data, member.id) 
        
        user["inventory"].append(processed_id)
        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"🎁 {member.mention} отримав **{templates[processed_id]['name']}**!")

async def setup(bot):
    await bot.add_cog(ItemsCog(bot))