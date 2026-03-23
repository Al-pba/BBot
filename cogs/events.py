import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import random
import os
from datetime import datetime
from utils import load_guild_json, save_guild_json

DATA_FILE = "users.json"
EVENTS_CONFIG = "events_config.json"

EVENT_CATEGORIES = {
    "economy": {
        "name": "Економіка та Гроші",
        "events": [
            "Ви знайшли загублений гаманець на вулиці.", "Банк помилково нарахував вам кешбек.", "Ви виграли у вуличну лотерею.", 
            "Хтось залишив решту в автоматі з кавою.", "Ви продали стару відеокарту на барахолці.", "Знайшли заначку в старій куртці.",
            "Податкова повернула вам частину коштів.", "Вам виплатили дивіденди за старі акції.", "Випадковий перехожий дав вам чайові.", "Ви знайшли рідкісну монету."
        ]
    },
    "tech": {
        "name": "IT та Технології",
        "events": [
            "Ви пофіксили критичний баг на сервері.", "Знайшли вразливість і отримали баунті.", "Вдало налаштували майнінг ферму.",
            "Оптимізували код і зекономили пам'ять.", "Хтось переплутав гаманці і скинув вам крипту.", "Виграли хакатон з програмування.",
            "Зібрали ПК з викинутих деталей.", "Вдало продали старий домен.", "Створили вірусний застосунок.", "Розшифрували старий жорсткий диск."
        ]
    },
    "crime": {
        "name": "Вулиці та Кримінал",
        "events": [
            "Ви відібрали гроші у місцевого хулігана.", "Знайшли чужу схованку (тайник).", "Обдурили вуличного наперсточника.",
            "Випадково знайшли валізу з готівкою.", "Допомогли мафії відмити кошти.", "Здали злочинця поліції за винагороду.",
            "Знайшли вкрадений телефон і повернули власнику.", "Виграли у підпільному покерному клубі.", "Врятували магазин від пограбування.", "Знайшли сейф у покинутому будинку."
        ]
    },
    "magic": {
        "name": "Магія та Містика",
        "events": [
            "Ви знайшли магічний кристал, що світиться.", "Допомогли алхіміку зібрати трави.", "Розгадали стародавню руну.",
            "Знайшли зілля удачі.", "Врятували духа, який віддячив золотом.", "Знайшли портал у скарбницю.",
            "Прочитали заклинання багатства.", "Знайшли чарівну паличку на горищі.", "Відьмак заплатив вам за інструкцію.", "Джин виконав ваше дрібне бажання."
        ]
    },
    "work": {
        "name": "Робота та Офіс",
        "events": [
            "Бос виписав вам несподівану премію.", "Ви перевиконали план на місяць.", "Знайшли конверт у столі колеги.",
            "Ваша ідея принесла компанії прибуток.", "Вас попросили вийти у вихідний за подвійну оплату.", "Клієнт залишив величезні чайові.",
            "Ви вдало завершили складний проєкт.", "Отримали бонус за вислугу років.", "Знайшли гроші під клавіатурою.", "Вам заплатили за мовчання про помилку боса."
        ]
    },
    "nature": {
        "name": "Природа та Виживання",
        "events": [
            "Викопали скарб у лісі.", "Знайшли рідкісний вид трюфеля.", "Врятували дику тварину, а поруч був скарб.",
            "Спіймали рідкісну рибу.", "Знайшли золотий пісок у річці.", "Зібрали унікальні мінерали.",
            "Знайшли покинутий табір золотошукачів.", "Пройшли небезпечний маршрут.", "Знайшли метеорит, що впав з неба.", "Врятували туриста і отримали нагороду."
        ]
    },
    "social": {
        "name": "Соціум та Допомога",
        "events": [
            "Допомогли бабусі перейти дорогу.", "Знайшли загубленого собаку багатія.", "Допомогли сусіду з ремонтом.",
            "Стали волонтером і отримали грант.", "Врятували кота з дерева.", "Допомогли туристу знайти дорогу.",
            "Організували успішний збір коштів.", "Знайшли ключі від авто і повернули власнику.", "Допомогли розвантажити меблі.", "Дали гарну пораду бізнесмену."
        ]
    },
    "casino": {
        "name": "Казино та Азарт",
        "events": [
            "Ви знайшли щасливу фішку казино.", "Зірвали міні-джекпот в старому автоматі.", "Вдало поставили на зеро.",
            "Знайшли загублений лотерейний білет (виграшний).", "Перемогли у суперечці на гроші.", "Виграли парі у бармена.",
            "Кинули монетку і вгадали 10 разів поспіль.", "Випадково зібрали флеш-рояль.", "Ваш кінь прийшов першим.", "Виграли у дартс на гроші."
        ]
    },
    "anomalies": {
        "name": "Аномалії та Фантастика",
        "events": [
            "НЛО загубило деталь, яку ви продали.", "З часового розлому випали гроші.", "Ви зустріли себе з майбутнього з готівкою.",
            "Гравітаційна аномалія притягнула сейф.", "Робот-кур'єр зламався і віддав вам посилку.", "Ви потрапили у паралельний вимір.",
            "Знайшли артефакт прибульців.", "З неба впав дощ із монет.", "Телепортувалися прямо у банківське сховище.", "Знайшли лазерну гармату."
        ]
    },
    "sport": {
        "name": "Спорт та Змагання",
        "events": [
            "Виграли вуличний забіг.", "Перемогли місцевого чемпіона з армреслінгу.", "Забили вирішальний гол.",
            "Знайшли гроші на трибунах стадіону.", "Виграли аматорський турнір.", "Вдало зробили ставку на спорт.",
            "Спіймали м'яч на бейсболі і продали фанату.", "Перемогли у боксерському спарингу.", "Пробігли марафон першим.", "Встановили новий світовий рекорд."
        ]
    }
}

class EventTaskModal(discord.ui.Modal, title="Швидке завдання!"):
    def __init__(self, target_word: str, reward: int, view: discord.ui.View):
        super().__init__()
        self.target_word = target_word
        self.reward = reward
        self.view_obj = view

        self.answer = discord.ui.TextInput(
            label=f"Введіть слово: {self.target_word}",
            placeholder="Вводьте сюди...",
            required=True
        )
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction):
        if self.answer.value.strip().lower() != self.target_word.lower():
            return await interaction.response.send_message("❌ Неправильне слово! Хтось інший ще може встигнути.", ephemeral=True)

        guild_id = interaction.guild.id
        data = load_guild_json(guild_id, DATA_FILE)
        uid = str(interaction.user.id)
        if uid not in data: data[uid] = {"balance": 0}
        data[uid]["balance"] = data[uid].get("balance", 0) + self.reward
        save_guild_json(guild_id, DATA_FILE, data)

        for child in self.view_obj.children:
            child.disabled = True
        
        await self.view_obj.message.edit(
            content=f"🎉 **{interaction.user.mention}** встиг першим виконати завдання і отримав `{self.reward} AC`!", 
            view=self.view_obj
        )
        await interaction.response.send_message(f"✅ Успіх! Ви отримали `{self.reward} AC`.", ephemeral=True)
        self.view_obj.stop()

class EventSpawnView(discord.ui.View):
    def __init__(self, reward: int):
        super().__init__(timeout=600) 
        self.reward = reward
        self.target_word = random.choice(["ШВИДКІСТЬ", "УДАЧА", "СКАРБ", "МОНЕТА", "УСПІХ", "РЕАКЦІЯ"])
        self.message = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="⏳ **Час вийшов!** Ніхто не встиг відреагувати на подію.", view=self)
        except:
            pass

    @discord.ui.button(label="Втрутитися (Забрати AC)", style=discord.ButtonStyle.success, emoji="⚡")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EventTaskModal(self.target_word, self.reward, self))

class EventWeightsSelect(discord.ui.Select):
    def __init__(self, cog, guild_id: int):
        self.cog = cog
        self.guild_id = guild_id
        
        options = []
        for key, cat_data in EVENT_CATEGORIES.items():
            options.append(discord.SelectOption(label=cat_data["name"], value=key))
            
        super().__init__(placeholder="Оберіть категорію для налаштування шансу...", options=options)

    async def callback(self, interaction: discord.Interaction):
        cat_key = self.values[0]
        await interaction.response.send_modal(WeightModal(self.guild_id, cat_key, EVENT_CATEGORIES[cat_key]["name"]))

class WeightModal(discord.ui.Modal):
    def __init__(self, guild_id: int, cat_key: str, cat_name: str):
        super().__init__(title="Налаштування шансів")
        self.guild_id = guild_id
        self.cat_key = cat_key
        
        self.weight_input = discord.ui.TextInput(
            label=f"Вага для '{cat_name}' (1-100)",
            placeholder="За замовчуванням: 10",
            default="10",
            required=True
        )
        self.add_item(self.weight_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            weight = int(self.weight_input.value)
            if weight < 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Введіть коректне число більше нуля.", ephemeral=True)

        config = load_guild_json(self.guild_id, EVENTS_CONFIG)
        if "weights" not in config: config["weights"] = {}
        config["weights"][self.cat_key] = weight
        save_guild_json(self.guild_id, EVENTS_CONFIG, config)
        
        await interaction.response.send_message(f"✅ Вагу для категорії встановлено на `{weight}`.", ephemeral=True)

class EventAdminView(discord.ui.View):
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ У вас немає прав адміністратора для використання цих кнопок.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Увімкнути/Вимкнути", style=discord.ButtonStyle.primary, row=0)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_guild_json(self.guild_id, EVENTS_CONFIG)
        current = config.get("is_enabled", False)
        config["is_enabled"] = not current
        save_guild_json(self.guild_id, EVENTS_CONFIG, config)
        
        state = "увімкнено" if config["is_enabled"] else "вимкнено"
        await interaction.response.send_message(f"🔄 Випадкові події тепер **{state}**.", ephemeral=True)

    @discord.ui.button(label="Встановити канал", style=discord.ButtonStyle.secondary, row=0)
    async def set_channel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_guild_json(self.guild_id, EVENTS_CONFIG)
        config["channel_id"] = interaction.channel.id
        save_guild_json(self.guild_id, EVENTS_CONFIG, config)
        await interaction.response.send_message(f"📍 Канал для подій встановлено: {interaction.channel.mention}", ephemeral=True)

    @discord.ui.button(label="Примусовий Спавн", style=discord.ButtonStyle.danger, row=0)
    async def force_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.cog.trigger_event(interaction.guild)
        await interaction.followup.send("⚡ Подію примусово запущено (якщо налаштовано канал)!")

    @discord.ui.button(label="Налаштувати шанси (Ваги)", style=discord.ButtonStyle.success, row=1)
    async def chances_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        view.add_item(EventWeightsSelect(self.cog, self.guild_id))
        await interaction.response.send_message("Оберіть категорію, щоб змінити її шанс появи (більша вага = частіше з'являється):", view=view, ephemeral=True)


class RandomEventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.events_loop.start()

    def cog_unload(self):
        self.events_loop.cancel()

    async def trigger_event(self, guild: discord.Guild):
        """Логіка генерації та відправки події"""
        config = load_guild_json(guild.id, EVENTS_CONFIG)
        channel_id = config.get("channel_id")
        if not channel_id: return
        
        channel = guild.get_channel(channel_id)
        if not channel: return

        weights_config = config.get("weights", {})
        categories = list(EVENT_CATEGORIES.keys())
        weights = [weights_config.get(cat, 10) for cat in categories]
        
        chosen_cat_key = random.choices(categories, weights=weights, k=1)[0]
        chosen_event_text = random.choice(EVENT_CATEGORIES[chosen_cat_key]["events"])
        reward = random.randint(10, 100)

        embed = discord.Embed(
            title=f"🎲 Випадкова подія: {EVENT_CATEGORIES[chosen_cat_key]['name']}",
            description=f"**{chosen_event_text}**\n\nХутчіш натисніть кнопку нижче та виконайте перевірку, щоб отримати `{reward} AC`!\n⏳ *У вас є рівно 10 хвилин.*",
            color=0x9b59b6
        )

        view = EventSpawnView(reward)
        msg = await channel.send(embed=embed, view=view)
        view.message = msg

        config["last_event_time"] = int(time.time())
        save_guild_json(guild.id, EVENTS_CONFIG, config)

    @tasks.loop(minutes=5)
    async def events_loop(self):
        """Цикл, який перевіряє ймовірності кожні 5 хвилин за динамічною кривою"""
        if not os.path.exists("server_data"): return
        
        current_time = int(time.time())
        now = datetime.now()
        
        is_prime_time = (8 <= now.hour < 12) or (17 <= now.hour < 19)

        for gid_str in os.listdir("server_data"):
            try:
                guild_id = int(gid_str)
                guild = self.bot.get_guild(guild_id)
                if not guild: continue

                config = load_guild_json(guild_id, EVENTS_CONFIG)
                
                if not config.get("is_enabled", False): continue
                
                last_time = config.get("last_event_time", 0)

                hours_since_last = (current_time - last_time) / 3600.0 if last_time > 0 else 8.0

                base_chance = ((hours_since_last / 8.0) ** 2) * 0.10
                
                spawn_chance = base_chance * 1.5 if is_prime_time else base_chance
                
                spawn_chance = min(0.50, spawn_chance)
                
                if random.random() < spawn_chance:
                    await self.trigger_event(guild)
                    
            except Exception as e:
                print(f"Помилка івенту: {e}")

    @events_loop.before_loop
    async def before_events(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="event_panel", description="[АДМІН] Панель керування випадковими подіями")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True) 
    @app_commands.guild_only()
    async def event_panel(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        config = load_guild_json(guild_id, EVENTS_CONFIG)
        
        is_enabled = "🟢 Увімкнено" if config.get("is_enabled", False) else "🔴 Вимкнено"
        channel_id = config.get("channel_id")
        channel_mention = f"<#{channel_id}>" if channel_id else "Не встановлено"
        
        current_time = int(time.time())
        last_time = config.get("last_event_time", 0)
        
        hours_passed = (current_time - last_time) / 3600.0 if last_time > 0 else 8.0
        current_chance = ((hours_passed / 8.0) ** 2) * 0.10
        if (8 <= datetime.now().hour < 12) or (17 <= datetime.now().hour < 19):
            current_chance *= 1.5
            
        chance_percent = min(50.0, current_chance * 100)

        embed = discord.Embed(title="⚙️ Панель керування: Випадкові події", color=0x34495e)
        embed.add_field(name="Статус", value=is_enabled, inline=True)
        embed.add_field(name="Канал", value=channel_mention, inline=True)
        embed.add_field(name="Остання подія", value=f"<t:{last_time}:R>" if last_time else "Ніколи", inline=True)
        embed.add_field(name="Динамічний шанс спавну", value=f"~`{chance_percent:.2f}%` кожні 5 хв", inline=False)
        
        weights = config.get("weights", {})
        weight_str = ", ".join([f"{EVENT_CATEGORIES[k]['name']}: {weights.get(k, 10)}" for k in list(EVENT_CATEGORIES.keys())[:3]]) + "..."
        embed.add_field(name="Налаштування ваг (Шансів)", value=weight_str, inline=False)
        embed.set_footer(text="Шанс автоматично росте по експоненті від часу останньої події.")

        await interaction.response.send_message(embed=embed, view=EventAdminView(self, guild_id), ephemeral=True)


async def setup(bot):
    await bot.add_cog(RandomEventsCog(bot))