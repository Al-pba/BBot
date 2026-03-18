import discord  
from discord.ext import commands
from discord import app_commands
import asyncio
import os
from dotenv import load_dotenv 
from collections import deque 
import traceback

# --- ІНТЕРФЕЙС КЛАСИ ДЛЯ HELP ---

class HelpDropdown(discord.ui.Select):
    def __init__(self, bot, categories):
        self.bot = bot
        self.categories = categories
        
        options = [
            discord.SelectOption(
                label=cat, 
                description=f"Переглянути команди категорії {cat}",
                emoji="📁"
            ) for cat in categories.keys()
        ]
        
        super().__init__(placeholder="Оберіть категорію команд...", min_values=1, max_values=1, options=options[:25]) # Додано [:25] для безпеки лімітів Discord

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        commands_list = self.categories[category]
        
        embed = discord.Embed(
            title=f"Категорія: {category}",
            description="\n".join(commands_list),
            color=0xCCFFCC 
        )
        embed.set_footer(text="Використовуйте '/' перед кожною командою")
        
        await interaction.response.edit_message(embed=embed)

class HelpView(discord.ui.View):
    def __init__(self, bot, categories, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id 
        self.add_item(HelpDropdown(bot, categories))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Ви не можете взаємодіяти з цим меню, оскільки його викликав інший гравець. Пропишіть `/help` самостійно.", ephemeral=True)
            return False
        return True

# --- ОСНОВНИЙ КЛАС БОТА ---

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!", 
            intents=discord.Intents.all(),
            help_command=None
        )
        self.logs_buffer = deque(maxlen=15)

    def add_custom_log(self, message: str):
        """Метод для додавання запису в логи з часовою міткою"""
        now = discord.utils.utcnow().strftime("%H:%M:%S")
        self.logs_buffer.append(f"[`{now}`] {message}")

    async def setup_hook(self):
        if not os.path.exists('./cogs'):
            os.makedirs('./cogs')

        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f'Завантажено ког: {filename}')
                except Exception as e:
                    print(f'Помилка завантаження {filename}: {e}')
        
        try:
            synced = await self.tree.sync()
            print(f"Успіх! Синхронізовано {len(synced)} слеш-команд(и).")
        except Exception as e:
            print(f"Помилка синхронізації команд: {e}")

bot = MyBot()

# --- ПОДІЇ ДЛЯ ЛОГУВАННЯ ---

@bot.event
async def on_ready():
    print("="*50)
    print(f'Бот {bot.user} успішно запущений!')
    print(f'Підключено до серверів: {len(bot.guilds)}')
    print("="*50)
    bot.add_custom_log("Бот запущений та готовий до роботи")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Глобальний обробник помилок для слеш-команд"""
    
    command_name = interaction.command.name if interaction.command else "Невідома команда"
    
    print("\n" + "="*50)
    print(f"ПОМИЛКА В КОМАНДІ: /{command_name}")
    print(f"Користувач: {interaction.user.display_name} ({interaction.user.id})")
    print(f"Сервер: {interaction.guild.name if interaction.guild else 'Особисті повідомлення'}")
    print("-" * 50)
    
    traceback.print_exception(type(error), error, error.__traceback__)
    print("="*50 + "\n")

    bot.add_custom_log(f"❌ Помилка в `/{command_name}` від {interaction.user.display_name}")

    user_msg = "❌ Ой, сталася внутрішня помилка. Розробник вже отримав чашку чаю, щоб пофіксити її!"
    
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(user_msg, ephemeral=True)
        else:
            await interaction.followup.send(user_msg, ephemeral=True)
    except discord.HTTPException:
        pass

@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command: app_commands.Command):
    """Автоматично логує кожне успішне використання слеш-команди"""
    log_msg = f"**{interaction.user.display_name}** використав `/{command.name}`"
    bot.add_custom_log(log_msg)

# --- КОМАНДИ ---

@bot.tree.command(name="help", description="Інтерактивне меню допомоги")
async def help_command(interaction: discord.Interaction):
    categories = {}
    
    for cmd in bot.tree.walk_commands():
        if isinstance(cmd, app_commands.Command) and cmd.parent is None:
            if cmd.binding:
                category_name = type(cmd.binding).__name__.replace("Cog", "")
            else:
                category_name = "Main"
                
            if category_name not in categories:
                categories[category_name] = []
                
            categories[category_name].append(f"**`/{cmd.name}`** — {cmd.description or 'Опис відсутній'}")

    if not categories:
        return await interaction.response.send_message("Наразі немає доступних команд.", ephemeral=True)

    main_embed = discord.Embed(
        title="BBot | Довідка",
        description="Оберіть категорію нижче для детальної інформації.",
        color=0xFDFD96 
    )
    main_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    
    main_embed.set_thumbnail(url=bot.user.display_avatar.url)
    
    await interaction.response.send_message(embed=main_embed, view=HelpView(bot, categories, interaction.user.id))

@bot.tree.command(name="logs", description="[Власник] Переглянути останні події")
async def logs(interaction: discord.Interaction):
    """Команда для перегляду логів у гарному форматі"""
    if not await bot.is_owner(interaction.user):
        return await interaction.response.send_message("❌ Ця команда доступна лише розробнику.", ephemeral=True)

    if not bot.logs_buffer:
        return await interaction.response.send_message("Журнал подій поки порожній.", ephemeral=True)

    log_content = "\n".join(bot.logs_buffer)
    
    embed = discord.Embed(
        title="📜 Журнал останніх подій",
        description=log_content,
        color=0xFFCFD2 
    )
    embed.set_footer(text=f"Всього записів: {len(bot.logs_buffer)}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- ЗАПУСК ---

async def main():
    load_dotenv() 
    token = os.getenv('DISCORD_TOKEN')
    
    if token is None:
        print("КРИТИЧНА ПОМИЛКА: DISCORD_TOKEN не знайдено!")
        return

    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())