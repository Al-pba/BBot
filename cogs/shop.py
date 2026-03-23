import discord
from discord.ext import commands, tasks
from discord import app_commands
from utils import load_guild_json, save_guild_json

DATA_FILE = "users.json"
ITEMS_TEMPLATES = "items_templates.json"
SHOP_FILE = "shop_stock.json"

RARITY_ORDER = {
    "міфічна": 6,
    "легендарна": 5,
    "епічна": 4,
    "рідкісна": 3,
    "незвичайна": 2,
    "звичайна": 1
}

class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def format_id(self, item_id: str) -> str:
        """Приводить ID до нижнього регістру та замінює пробіли на підкреслення."""
        return item_id.lower().strip().replace(" ", "_")

    def get_user(self, data, uid):
        """Безпечно отримує дані юзера, ініціалізуючи відсутні поля."""
        uid = str(uid)
        if uid not in data:
            data[uid] = {}
        data[uid].setdefault("balance", 0)
        data[uid].setdefault("inventory", [])
        return data[uid]

    def get_rarity_weight(self, rarity_str: str) -> int:
        """Отримує вагу рідкості для сортування"""
        if not rarity_str: 
            return 0
        return RARITY_ORDER.get(rarity_str.lower().strip(), 0)

    @app_commands.command(name="shop_remove", description="Видалити предмет з вітрини магазину")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def shop_remove(self, interaction: discord.Interaction, item_id: str):
        guild_id = interaction.guild.id
        processed_id = self.format_id(item_id)
        shop = load_guild_json(guild_id, SHOP_FILE)
        
        if processed_id in shop:
            del shop[processed_id]
            save_guild_json(guild_id, SHOP_FILE, shop)
            await interaction.response.send_message(f"Предмет `{processed_id}` прибрано з магазину.")
        else:
            await interaction.response.send_message("Цього предмета немає в магазині.", ephemeral=True)


    @app_commands.command(name="shop", description="Показати товари в магазині")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        shop = load_guild_json(guild_id, SHOP_FILE)
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        if not shop:
            return await interaction.response.send_message("🛒 Магазин порожній. Зайдіть пізніше!", ephemeral=True)

        embed = discord.Embed(title="🛒 Міський Магазин", color=discord.Color.blue())
        embed.set_footer(text="Купити: /buy <ID> | Продати: /sell <ID>")

        shop_items = []
        for i_id, info in shop.items():
            item = templates.get(i_id)
            if item:
                shop_items.append((i_id, info, item))

        shop_items.sort(key=lambda x: self.get_rarity_weight(x[2].get('rarity', '')), reverse=True)

        fields_count = 0
        for i_id, info, item in shop_items:
            if fields_count >= 25: break
            
            stock_text = "∞ (Нескінченно)" if info['stock'] == -1 else f"{info['stock']} шт."
            embed.add_field(
                name=f"{item['rarity'].capitalize()} {item['name']}",
                value=f"🆔 ID: `{i_id}`\n💰 Купівля: `{info['price']} AC`\n💵 Продаж: `{info['sell_price']} AC`\n📦 В наявності: {stock_text}",
                inline=True
            )
            fields_count += 1
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Купити предмет")
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction, item_id: str, amount: int = 1):
        if amount <= 0: 
            return await interaction.response.send_message("Кількість має бути 1 або більше.", ephemeral=True)
        
        guild_id = interaction.guild.id
        processed_id = self.format_id(item_id)
        shop = load_guild_json(guild_id, SHOP_FILE)
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        if processed_id not in shop:
            return await interaction.response.send_message("Цього товару немає в магазині.", ephemeral=True)
        
        item_shop = shop[processed_id]
        total_cost = item_shop["price"] * amount
        
        data = load_guild_json(guild_id, DATA_FILE)
        user = self.get_user(data, interaction.user.id)

        if user["balance"] < total_cost:
            return await interaction.response.send_message(f"Недостатньо AC! Треба `{total_cost}`, а у вас `{user['balance']}`.", ephemeral=True)

        if item_shop["stock"] != -1:
            if item_shop["stock"] < amount:
                return await interaction.response.send_message(f"В наявності лише {item_shop['stock']} шт.!", ephemeral=True)
            shop[processed_id]["stock"] -= amount

        user["balance"] -= total_cost
        user["inventory"].extend([processed_id] * amount) 

        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, SHOP_FILE, shop)
        
        await interaction.response.send_message(f"Ви купили **{templates[processed_id]['name']}** (x{amount}) за `{total_cost} AC`!")

    @app_commands.command(name="sell", description="Продати предмет з рюкзака назад у магазин")
    @app_commands.guild_only()
    async def sell(self, interaction: discord.Interaction, item_id: str, amount: int = 1):
        if amount <= 0: 
            return await interaction.response.send_message("Кількість має бути 1 або більше.", ephemeral=True)
        
        guild_id = interaction.guild.id
        processed_id = self.format_id(item_id)
        shop = load_guild_json(guild_id, SHOP_FILE)
        data = load_guild_json(guild_id, DATA_FILE)
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        
        user = self.get_user(data, interaction.user.id)
        
        if user["inventory"].count(processed_id) < amount:
            return await interaction.response.send_message(f"У вас немає {amount} шт. предмета `{processed_id}`.", ephemeral=True)

        if processed_id not in shop:
            return await interaction.response.send_message("Магазин не скуповує цей товар. (Його немає в асортименті).", ephemeral=True)

        sell_reward = shop[processed_id]["sell_price"] * amount
        
        for _ in range(amount):
            user["inventory"].remove(processed_id)
        
        user["balance"] += sell_reward
        
        if shop[processed_id]["stock"] != -1:
            shop[processed_id]["stock"] += amount

        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, SHOP_FILE, shop)
        
        item_name = templates.get(processed_id, {}).get("name", processed_id)
        await interaction.response.send_message(f"💵 Ви продали **{item_name}** (x{amount}) за `{sell_reward} AC`! Товар повернувся на полиці магазину.")

    @app_commands.command(name="shop_add", description="[Адмін] Додати предмет у магазин")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def shop_add(self, interaction: discord.Interaction, item_id: str, price: int, sell_price: int, stock: int = -1):
        guild_id = interaction.guild.id
        processed_id = self.format_id(item_id)
        
        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        if processed_id not in templates:
            return await interaction.response.send_message(f"Предмета `{processed_id}` немає в базі шаблонів!", ephemeral=True)

        shop = load_guild_json(guild_id, SHOP_FILE)
        shop[processed_id] = {
            "price": price,
            "sell_price": sell_price,
            "stock": stock
        }
        
        save_guild_json(guild_id, SHOP_FILE, shop)
        await interaction.response.send_message(
            f"Предмет **{templates[processed_id]['name']}** додано в магазин!\n"
            f"💰 Ціна: `{price} AC` | 💵 Викуп: `{sell_price} AC` | 📦 Сток: {'∞' if stock == -1 else stock}"
        )

    @app_commands.command(name="shop_restock", description="[Адмін] Поповнити кількість товару в магазині")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def shop_restock(self, interaction: discord.Interaction, item_id: str, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("Кількість для поповнення має бути більшою за 0.", ephemeral=True)

        guild_id = interaction.guild.id
        processed_id = self.format_id(item_id)
        shop = load_guild_json(guild_id, SHOP_FILE)

        if processed_id not in shop:
            return await interaction.response.send_message(f"Предмета `{processed_id}` немає в асортименті магазину!", ephemeral=True)

        if shop[processed_id]["stock"] == -1:
            return await interaction.response.send_message(f"📦 Предмет `{processed_id}` і так має нескінченний запас.", ephemeral=True)

        shop[processed_id]["stock"] += amount
        save_guild_json(guild_id, SHOP_FILE, shop)

        templates = load_guild_json(guild_id, ITEMS_TEMPLATES)
        item_name = templates.get(processed_id, {}).get("name", processed_id)

        emb = discord.Embed(title="📦 Поповнення складу", color=0x3498db)
        emb.description = (
            f"Запаси товару **{item_name}** успішно поповнено!\n"
            f"📥 Додано: `{amount} шт.`\n"
            f"📊 Поточний запас: `{shop[processed_id]['stock']} шт.`"
        )
        await interaction.response.send_message(embed=emb)


async def setup(bot):
    await bot.add_cog(ShopCog(bot))