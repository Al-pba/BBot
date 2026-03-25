import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import random
import os
from datetime import time as dt_time, timezone, timedelta

from cogs.monopoly import PROFESSIONS, get_monopoly_data, add_to_storage 
from utils import load_guild_json, save_guild_json

DATA_FILE = "users.json"
MONOPOLY_FILE = "monopoly.json"
ECONOMY_CONFIG = "economy_config.json"

PROFESSIONS_INFO = {
    "робітник": "Залежить від тілобудови (1-4 год)",
    "менеджер": "Залежить від тілобудови (6-8 год)",
    "агроном": "Залежить від тілобудови (6-8 год)",
    "логіст": "Залежить від тілобудови (1-4 год)",
    "охоронець": "Залежить від тілобудови (6-8 год)"
}

def calc_success_chance(stat: int) -> float:
    stat = max(1, min(100, stat))
    chance = 30 + ((stat - 1) / 99) * 30
    return chance / 100.0

def calc_cd_4_1(stat: int) -> int:
    stat = max(1, min(100, stat))
    hours = 4 - ((stat - 1) / 99) * 3
    return int(hours * 3600)

def calc_cd_8_6(stat: int) -> int:
    stat = max(1, min(100, stat))
    hours = 8 - ((stat - 1) / 99) * 2
    return int(hours * 3600)

def calc_buff_duration_2_6(stat: int) -> int:
    stat = max(1, min(100, stat))
    hours = 2 + ((stat - 1) / 99) * 4
    return int(hours * 3600)

def calc_manager_success_bonus(stat: int) -> float:
    stat = max(1, min(100, stat))
    bonus = 10 + ((stat - 1) / 99) * 40
    return bonus / 100.0

def calc_logistic_transfer(stat: int) -> float:
    stat = max(1, min(100, stat))
    transfer = 30 + ((stat - 1) / 99) * 30
    return transfer / 100.0



class ApplicationView(discord.ui.View):
    def __init__(self, cog: commands.Cog, applicant_id: str, comp_owner_id: str, prop_id: str, profession: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.applicant_id = applicant_id
        self.comp_owner_id = comp_owner_id
        self.prop_id = prop_id
        self.profession = profession

    @discord.ui.button(label="Прийняти", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.comp_owner_id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Тільки власник компанії може приймати рішення.", ephemeral=True)

        guild = interaction.guild
        data = load_guild_json(guild.id, DATA_FILE)
        mono_data = load_guild_json(guild.id, MONOPOLY_FILE)

        applicant_data = self.cog.get_user(data, self.applicant_id)
        if applicant_data.get("job", {}).get("company_id"):
            for child in self.children: child.disabled = True
            return await interaction.response.edit_message(content=f"⚠️ Гравець <@{self.applicant_id}> вже знайшов іншу роботу.", view=self)

        comp = mono_data["companies"].get(self.comp_owner_id)
        if not comp:
            return await interaction.response.send_message("Вашої компанії більше не існує.", ephemeral=True)
            
        prop = comp["properties"].get(self.prop_id)
        if not prop:
            return await interaction.response.send_message("Цього майна більше не існує.", ephemeral=True)

        prof_limit = prop.get("vacancy_limits", {}).get(self.profession, 1)
        current_prof_workers = sum(1 for p in prop.get("workers", {}).values() if p == self.profession)
        
        if current_prof_workers >= prof_limit:
            return await interaction.response.send_message(f"Всі {prof_limit} місць на посаду '{self.profession.capitalize()}' вже зайняті!", ephemeral=True)

        if "workers" not in prop: prop["workers"] = {}
        prop["workers"][self.applicant_id] = self.profession
        
        applicant_data["job"] = {
            "company_id": self.comp_owner_id,
            "prop_id": self.prop_id,
            "profession": self.profession
        }
        applicant_data["pending_apps"] = []

        save_guild_json(guild.id, DATA_FILE, data)
        save_guild_json(guild.id, MONOPOLY_FILE, mono_data)

        channel = guild.get_channel(comp["channel_id"])
        if channel:
            member = guild.get_member(int(self.applicant_id))
            if member:
                await channel.set_permissions(member, read_messages=True, send_messages=True)
                await channel.send(f"🎉 Вітаємо нового працівника {member.mention} на посаді **{self.profession.capitalize()}**!")

        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"Ви прийняли <@{self.applicant_id}> на посаду {self.profession.capitalize()}.", view=self)

    @discord.ui.button(label="Відхилити", style=discord.ButtonStyle.danger, emoji="✖️")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.comp_owner_id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Тільки власник компанії може приймати рішення.", ephemeral=True)

        guild = interaction.guild
        data = load_guild_json(guild.id, DATA_FILE)
        
        applicant_data = self.cog.get_user(data, self.applicant_id)
        if "pending_apps" in applicant_data:
            applicant_data["pending_apps"] = [app for app in applicant_data["pending_apps"] if app != self.prop_id]
            save_guild_json(guild.id, DATA_FILE, data)

        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"Ви відмовили <@{self.applicant_id}>.", view=self)

        member = guild.get_member(int(self.applicant_id))
        if member:
            try: await member.send(f"Вашу заявку на роботу у фірмі відхилено.")
            except: pass

class NavBackButton(discord.ui.Button):
    def __init__(self, target_step: str, view_obj):
        super().__init__(label="🔙 Назад", style=discord.ButtonStyle.secondary, row=1)
        self.target_step = target_step
        self.nav_view = view_obj

    async def callback(self, interaction: discord.Interaction):
        if self.target_step == "companies":
            self.nav_view.selected_owner = None
            await self.nav_view.show_companies(interaction)
        elif self.target_step == "properties":
            self.nav_view.selected_prop = None
            await self.nav_view.show_properties(interaction)


class ProfessionSelect(discord.ui.Select):
    def __init__(self, view_obj):
        self.nav_view = view_obj
        options = []
        owner_id = view_obj.selected_owner
        prop_id = view_obj.selected_prop
        prop = view_obj.mono_data["companies"][owner_id]["properties"][prop_id]
        
        for prof in view_obj.vacancies_tree[owner_id][prop_id]:
            salary = prop.get("salaries", {}).get(prof, 100)
            mode = "🟢 Відкритий" if prop.get("hiring_mode") == "open" else "🟡 Заявка"
            cd = PROFESSIONS_INFO.get(prof, "Невідомо")
            
            options.append(discord.SelectOption(
                label=prof.capitalize(),
                value=prof,
                description=f"ЗП: {salary} AC | КД: {cd} | Набір: {mode}",
                emoji="💼"
            ))

        super().__init__(placeholder="Крок 3: Оберіть посаду...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        owner_id = self.nav_view.selected_owner
        prop_id = self.nav_view.selected_prop
        prof = self.values[0]
        
        guild = interaction.guild
        user_id = str(interaction.user.id)
        
        data = load_guild_json(guild.id, DATA_FILE)
        mono_data = load_guild_json(guild.id, MONOPOLY_FILE)
        user_data = self.nav_view.cog.get_user(data, user_id)
        
        if user_id == owner_id:
            return await interaction.response.send_message("Ви не можете працювати самі у себе як найманий робітник.", ephemeral=True)

        if user_data.get("job", {}).get("company_id"):
            return await interaction.response.send_message("Ви вже працевлаштовані! Спочатку звільніться (/job_leave).", ephemeral=True)

        comp = mono_data["companies"].get(owner_id)
        prop = comp["properties"].get(prop_id)
        
        prof_limit = prop.get("vacancy_limits", {}).get(prof, 1)
        current_prof_workers = sum(1 for p in prop.get("workers", {}).values() if p == prof)
        if current_prof_workers >= prof_limit:
            return await interaction.response.send_message(f"На жаль, всі {prof_limit} місць на посаду '{prof.capitalize()}' вже зайняті.", ephemeral=True)

        if prop.get("hiring_mode") == "open":
            if "workers" not in prop: prop["workers"] = {}
            prop["workers"][user_id] = prof
            
            user_data["job"] = {"company_id": owner_id, "prop_id": prop_id, "profession": prof}
            user_data["pending_apps"] = []
            
            save_guild_json(guild.id, DATA_FILE, data)
            save_guild_json(guild.id, MONOPOLY_FILE, mono_data)
            
            channel = guild.get_channel(comp["channel_id"])
            if channel:
                await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
                await channel.send(f"🎉 Вітаємо нового працівника {interaction.user.mention} на посаді **{prof.capitalize()}** (Об'єкт: {prop['name']})!")
            
            embed = discord.Embed(title="Працевлаштування успішне!", description=f"Ви успішно влаштувалися у **{comp['name']}** на посаду **{prof.capitalize()}**!", color=0x2ecc71)
            return await interaction.response.edit_message(embed=embed, view=None)

        else:
            if "pending_apps" not in user_data: user_data["pending_apps"] = []
            if prop_id in user_data["pending_apps"]:
                return await interaction.response.send_message("⚠️ Ви вже подали заявку на цей об'єкт. Очікуйте відповіді роботодавця.", ephemeral=True)
            
            if len(user_data["pending_apps"]) >= 3:
                return await interaction.response.send_message("Ви не можете мати більше 3 активних заявок одночасно.", ephemeral=True)

            user_data["pending_apps"].append(prop_id)
            save_guild_json(guild.id, DATA_FILE, data)

            channel = guild.get_channel(comp["channel_id"])
            if channel:
                view = ApplicationView(self.nav_view.cog, user_id, owner_id, prop_id, prof)
                salary = prop.get("salaries", {}).get(prof, 100)
                await channel.send(
                    f"**Нова заявка на роботу!**\n"
                    f"Гравець {interaction.user.mention} хоче працювати на об'єкті **{prop['name']}**.\n"
                    f"Посада: {prof.capitalize()} | Запропонована ЗП: {salary} AC",
                    view=view
                )
            
            embed = discord.Embed(title="Заявку надіслано!", description=f"Вашу заявку успішно надіслано до компанії **{comp['name']}**! Очікуйте відповіді.", color=0xf1c40f)
            return await interaction.response.edit_message(embed=embed, view=None)

class PropertySelect(discord.ui.Select):
    def __init__(self, view_obj):
        self.nav_view = view_obj
        options = []
        owner_id = view_obj.selected_owner
        
        for prop_id in view_obj.vacancies_tree[owner_id].keys():
            prop_name = view_obj.mono_data["companies"][owner_id]["properties"][prop_id]["name"]
            prop_type = view_obj.mono_data["companies"][owner_id]["properties"][prop_id]["type"]
            options.append(discord.SelectOption(
                label=prop_name, 
                value=prop_id, 
                description=f"Тип: {prop_type.capitalize()}", 
                emoji="🏭"
            ))
            
        super().__init__(placeholder="Крок 2: Оберіть об'єкт...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        self.nav_view.selected_prop = self.values[0]
        await self.nav_view.show_professions(interaction)

class CompanySelect(discord.ui.Select):
    def __init__(self, view_obj):
        self.nav_view = view_obj
        options = []
        
        for owner_id in view_obj.vacancies_tree.keys():
            comp_name = view_obj.mono_data["companies"][owner_id]["name"]
            options.append(discord.SelectOption(
                label=comp_name, 
                value=owner_id, 
                emoji="🏢"
            ))
            
        super().__init__(placeholder="Крок 1: Оберіть компанію...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        self.nav_view.selected_owner = self.values[0]
        await self.nav_view.show_properties(interaction)

class JobNavView(discord.ui.View):
    def __init__(self, cog, vacancies_tree, mono_data):
        super().__init__(timeout=180)
        self.cog = cog
        self.vacancies_tree = vacancies_tree
        self.mono_data = mono_data
        
        self.selected_owner = None
        self.selected_prop = None
        
        self.add_item(CompanySelect(self))

    async def show_companies(self, interaction: discord.Interaction):
        self.clear_items()
        self.add_item(CompanySelect(self))
        
        embed = discord.Embed(
            title="📋 Біржа Праці",
            description=f"Знайдено компаній з відкритими вакансіями: **{len(self.vacancies_tree)}**\n*Оберіть компанію зі списку нижче, щоб розпочати.*",
            color=0x3498db
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def show_properties(self, interaction: discord.Interaction):
        self.clear_items()
        self.add_item(PropertySelect(self))
        self.add_item(NavBackButton("companies", self))
        
        comp_name = self.mono_data["companies"][self.selected_owner]["name"]
        embed = discord.Embed(
            title="📋 Біржа Праці",
            description=f"🏢 Компанія: **{comp_name}**\n*Оберіть об'єкт нерухомості зі списку нижче.*",
            color=0x3498db
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def show_professions(self, interaction: discord.Interaction):
        self.clear_items()
        self.add_item(ProfessionSelect(self))
        self.add_item(NavBackButton("properties", self))
        
        comp_name = self.mono_data["companies"][self.selected_owner]["name"]
        prop_name = self.mono_data["companies"][self.selected_owner]["properties"][self.selected_prop]["name"]
        embed = discord.Embed(
            title="📋 Біржа Праці",
            description=f"🏢 Компанія: **{comp_name}**\n🏭 Об'єкт: **{prop_name}**\n*Оберіть вакансію (професію) зі списку нижче.*",
            color=0x3498db
        )
        await interaction.response.edit_message(embed=embed, view=self)

class WorkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_stat_boost.start()

    def get_user(self, data, uid):
        uid = str(uid)
        if uid not in data: data[uid] = {}
        data[uid].setdefault("balance", 0)
        data[uid].setdefault("job", {})
        data[uid].setdefault("pending_apps", [])
        data[uid].setdefault("stats", {"strength": 1, "agility": 1, "physique": 1, "intelligence": 1, "wisdom": 1, "charisma": 1})
        data[uid].setdefault("work_cooldown", 0)
        data[uid].setdefault("worked_today", {})
        return data[uid]

    @tasks.loop(time=dt_time(hour=3, minute=0, tzinfo=timezone(timedelta(hours=2))))
    async def daily_stat_boost(self):
        """О 3-й ночі прокачує статки гравцям, які працювали"""
        for gid in os.listdir("server_data"):
            try:
                guild_id = int(gid)
                data = load_guild_json(guild_id, DATA_FILE)
                updated = False
                
                for uid, user_data in data.items():
                    worked = user_data.get("worked_today", {})
                    if worked:
                        stats = user_data.get("stats", {})
                        for stat_name in worked.keys():
                            if stat_name in stats and stats[stat_name] < 100:
                                stats[stat_name] += 1
                        user_data["worked_today"] = {} 
                        updated = True
                
                if updated:
                    save_guild_json(guild_id, DATA_FILE, data)
            except Exception as e:
                print(f"Помилка 3AM boost: {e}")

    @app_commands.command(name="work", description="Почати робочу зміну")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        data = load_guild_json(guild_id, DATA_FILE)
        mono = get_monopoly_data(guild_id)
        
        user_data = self.get_user(data, user_id)
        job = user_data.get("job", {})
        
        if not job:
            return await interaction.response.send_message("Ви безробітний. Знайдіть роботу через `/vacancies`.", ephemeral=True)

        if time.time() < user_data["work_cooldown"]:
            left = int(user_data["work_cooldown"] - time.time())
            return await interaction.response.send_message(f"⏳ Ви втомилися. Наступна зміна буде доступна <t:{int(user_data['work_cooldown'])}:R>.", ephemeral=True)

        comp_owner = job["company_id"]
        prop_id = job["prop_id"]
        prof = job["profession"]
        
        comp = mono.get("companies", {}).get(comp_owner)
        if not comp or prop_id not in comp.get("properties", {}):
            return await interaction.response.send_message("Вашої компанії або робочого місця більше не існує.", ephemeral=True)

        prop = comp["properties"][prop_id]
        
        if prop.get("buffs", {}).get("disabled_until", 0) > time.time():
            return await interaction.response.send_message("⚡ На об'єкті зараз немає світла (іде ремонт або сталась аварія)! Робота призупинена.", ephemeral=True)

        salary_to_pay = prop.get("salaries", {}).get(prof, 100)
        stats = user_data["stats"]

        comp_channel = None
        if comp.get("channel_id"):
            comp_channel = interaction.guild.get_channel(comp["channel_id"])

        # ==========================================
        # 1. РОБІТНИК (Завод, Ферма, Офіс)
        # ==========================================
        if prof == "робітник" and prop["type"] in ["завод", "ферма", "офіс"]:
            main_stat = stats.get("intelligence", 1) if prop["type"] == "офіс" else stats.get("strength", 1)
            attempts = max(1, main_stat) 
            
            res_type = "materials" if prop["type"] == "завод" else "crops" if prop["type"] == "ферма" else "data"

            if comp_owner == "STATE_COMPANY":
                config = load_guild_json(guild_id, ECONOMY_CONFIG)
                if config.get("server_bank", 0) < salary_to_pay:
                    return await interaction.response.send_message(f"У Державній Казні недостатньо грошей для оплати ({salary_to_pay} AC).", ephemeral=True)
                config["server_bank"] -= salary_to_pay
                save_guild_json(guild_id, ECONOMY_CONFIG, config)
            else:
                current_reserve = prop.get("reserve", 0)
                if current_reserve < salary_to_pay:
                    return await interaction.response.send_message(f"❌ Бюджет об'єкта порожній! Роботодавець не поповнив резерв (Потрібно: {salary_to_pay} AC), тому робота зупинена.", ephemeral=True)
                prop["reserve"] = current_reserve - salary_to_pay

            buffs = prop.get("buffs", {})
            success_bonus = 0
            extra_yield = 0
            if buffs.get("manager_expires", 0) > time.time():
                success_bonus = buffs.get("success_bonus", 0)
                extra_yield = buffs.get("extra_yield", 0)

            base_success_chance = calc_success_chance(main_stat)
            final_success_chance = min(1.0, base_success_chance + success_bonus)

            defects, successes = 0, 0
            for _ in range(attempts):
                if random.random() < final_success_chance: successes += 1
                else: defects += 1

            total_produced = successes * (1 + extra_yield)

            remaining = add_to_storage(comp_owner, mono, prop_id, res_type, total_produced)
            actual_added = total_produced - remaining
            
            if actual_added == 0:
                if comp_owner == "STATE_COMPANY":
                    config = load_guild_json(guild_id, ECONOMY_CONFIG)
                    config["server_bank"] += salary_to_pay
                    save_guild_json(guild_id, ECONOMY_CONFIG, config)
                else:
                    prop["reserve"] += salary_to_pay
                return await interaction.response.send_message("❌ Всі склади переповнені! Ви не можете виготовити продукцію, поки керівник не звільнить місце.", ephemeral=True)
            
            total_produced = actual_added # Гравець отримав лише те, що влізло
            
            user_data["balance"] += salary_to_pay

            cd = calc_cd_4_1(stats.get("physique", 1))
            user_data["work_cooldown"] = int(time.time()) + cd
            user_data.setdefault("worked_today", {})["physique"] = True
            user_data["worked_today"]["strength" if res_type != "data" else "intelligence"] = True

            save_guild_json(guild_id, DATA_FILE, data)
            save_guild_json(guild_id, MONOPOLY_FILE, mono)

            res_names_ua = {"materials": "деталей (матеріалів)", "crops": "одиниць врожаю", "data": "пакетів даних"}
            res_display = res_names_ua.get(res_type, res_type)

            if comp_channel:
                await comp_channel.send(f"👷 **{interaction.user.display_name}** відпрацював зміну на **{prop['name']}**.\n💵 ЗП: `{salary_to_pay} AC` | 📦 Виготовлено: `{total_produced}` {res_display}.")

            embed = discord.Embed(title=f"🏭 Зміна завершена: {prop['name']}", color=0x2ecc71)
            embed.add_field(name="💰 Зароблено", value=f"`{salary_to_pay} AC`", inline=True)
            embed.add_field(name="📦 Виготовлено", value=f"`{total_produced}` {res_display}", inline=True)
            embed.add_field(name="⚠️ Браковано/Не влізло", value=f"`{defects + remaining}` шт.", inline=True)
            embed.set_footer(text=f"Статистика: {successes} успішних виготовлень із {attempts} спроб.")
            embed.description = f"⏳ Наступна зміна буде доступна <t:{int(time.time()) + cd}:R>"
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        elif prof == "робітник" and prop["type"] == "сервер":
            connected_to_id = prop.get("connected_to")
            if not connected_to_id: return await interaction.response.send_message("Цей сервер не підключений до жодного офісу!", ephemeral=True)
            
            target_office = comp["properties"].get(connected_to_id)
            if not target_office or target_office["type"] != "офіс": return await interaction.response.send_message("Сервер має бути підключений до офісу!", ephemeral=True)

            if comp_owner == "STATE_COMPANY":
                config = load_guild_json(guild_id, ECONOMY_CONFIG)
                if config.get("server_bank", 0) < salary_to_pay: return await interaction.response.send_message("У Державній Казні немає грошей на вашу ЗП.", ephemeral=True)
                config["server_bank"] -= salary_to_pay
                save_guild_json(guild_id, ECONOMY_CONFIG, config)
            else:
                current_reserve = prop.get("reserve", 0)
                if current_reserve < salary_to_pay:
                    return await interaction.response.send_message(f"❌ Бюджет сервера порожній! Роботодавець не поповнив резерв (Потрібно: {salary_to_pay} AC).", ephemeral=True)
                prop["reserve"] = current_reserve - salary_to_pay

            boost_percent = stats.get("intelligence", 1) / 100.0
            current_data = target_office.get("storage", {}).get("data", 0)
            bonus_data = max(1, int(current_data * boost_percent))
            
            remaining = add_to_storage(comp_owner, mono, connected_to_id, "data", bonus_data)
            actual_added = bonus_data - remaining
            
            if actual_added == 0:
                if comp_owner == "STATE_COMPANY":
                    config = load_guild_json(guild_id, ECONOMY_CONFIG)
                    config["server_bank"] += salary_to_pay
                    save_guild_json(guild_id, ECONOMY_CONFIG, config)
                else:
                    prop["reserve"] += salary_to_pay
                return await interaction.response.send_message("❌ Всі склади офісу переповнені! Оптимізація не дасть результатів.", ephemeral=True)

            user_data["balance"] += salary_to_pay
            cd = calc_cd_4_1(stats.get("wisdom", 1))
            user_data["work_cooldown"] = int(time.time()) + cd
            user_data.setdefault("worked_today", {})["wisdom"] = True
            
            save_guild_json(guild_id, DATA_FILE, data)
            save_guild_json(guild_id, MONOPOLY_FILE, mono)
            
            if comp_channel:
                await comp_channel.send(f"💻 **{interaction.user.display_name}** оптимізував сервери для **{target_office['name']}**.\n💵 ЗП: `{salary_to_pay} AC` | 📊 Бонус даних: `{actual_added}`.")

            return await interaction.response.send_message(f"💻 Ви оптимізували сервери! Згенеровано `{actual_added}` додаткових даних для офісу.\nЗарплата: `{salary_to_pay} AC`.\n⏳ Наступна зміна <t:{int(time.time()) + cd}:R>", ephemeral=True)

        # ==========================================
        # 3 & 4. МЕНЕДЖЕР ТА АГРОНОМ
        # ==========================================
        elif prof in ["менеджер", "агроном"]:
            if comp_owner == "STATE_COMPANY":
                config = load_guild_json(guild_id, ECONOMY_CONFIG)
                if config.get("server_bank", 0) < salary_to_pay: return await interaction.response.send_message("У Казні немає грошей.", ephemeral=True)
                config["server_bank"] -= salary_to_pay
                save_guild_json(guild_id, ECONOMY_CONFIG, config)
            else:
                current_reserve = prop.get("reserve", 0)
                if current_reserve < salary_to_pay:
                    return await interaction.response.send_message(f"❌ Бюджет об'єкта порожній! Роботодавець не поповнив резерв (Потрібно: {salary_to_pay} AC).", ephemeral=True)
                prop["reserve"] = current_reserve - salary_to_pay
                
            user_data["balance"] += salary_to_pay

            main_stat = stats.get("wisdom", 1) if prof == "агроном" else stats.get("charisma", 1)
            duration_secs = calc_buff_duration_2_6(main_stat)
            
            success_bonus = calc_manager_success_bonus(main_stat)
            extra_yield = 3 if main_stat > 50 else 2

            if "buffs" not in prop: prop["buffs"] = {}
            prop["buffs"]["manager_expires"] = int(time.time()) + duration_secs
            prop["buffs"]["success_bonus"] = success_bonus
            prop["buffs"]["extra_yield"] = extra_yield

            cd = calc_cd_8_6(stats.get("physique", 1))
            user_data["work_cooldown"] = int(time.time()) + cd
            user_data.setdefault("worked_today", {})["physique"] = True
            user_data["worked_today"]["wisdom" if prof == "агроном" else "charisma"] = True

            save_guild_json(guild_id, DATA_FILE, data)
            save_guild_json(guild_id, MONOPOLY_FILE, mono)
            
            hours = round(duration_secs / 3600, 1)
            
            if comp_channel:
                await comp_channel.send(f"📈 **{interaction.user.display_name}** провів мотивуючий тренінг на **{prop['name']}** (Баф на {hours} год).\n💵 ЗП: `{salary_to_pay} AC`.")

            return await interaction.response.send_message(f"📈 Баф накладено на {hours} год!\nШанс успіху робітників: `+{int(success_bonus*100)}%`, Бонус видобутку: `+{extra_yield}`.\nЗарплата: `{salary_to_pay} AC`.\n⏳ Наступна зміна <t:{int(time.time()) + cd}:R>", ephemeral=True)

        # ==========================================
        # 5. ЛОГІСТ (Склад)
        # ==========================================
        elif prof == "логіст" and prop["type"] == "склад":
            if comp_owner == "STATE_COMPANY":
                config = load_guild_json(guild_id, ECONOMY_CONFIG)
                if config.get("server_bank", 0) < salary_to_pay: return await interaction.response.send_message("У Казні немає грошей.", ephemeral=True)
                config["server_bank"] -= salary_to_pay
                save_guild_json(guild_id, ECONOMY_CONFIG, config)
            else:
                current_reserve = prop.get("reserve", 0)
                if current_reserve < salary_to_pay:
                    return await interaction.response.send_message(f"❌ Бюджет складу порожній! Роботодавець не поповнив резерв (Потрібно: {salary_to_pay} AC).", ephemeral=True)
                prop["reserve"] = current_reserve - salary_to_pay
                
            user_data["balance"] += salary_to_pay

            transfer_pct = calc_logistic_transfer(stats.get("agility", 1))
            transferred_totals = {"materials": 0, "crops": 0, "data": 0}
            
            for p_id, p_data in comp["properties"].items():
                if p_data.get("connected_to") == prop_id:
                    for r_type in ["materials", "crops", "data"]:
                        amt = p_data.get("storage", {}).get(r_type, 0)
                        if amt > 0:
                            move_amt = max(1, int(amt * transfer_pct))
                            remaining = add_to_storage(comp_owner, mono, prop_id, r_type, move_amt)
                            actual_moved = move_amt - remaining
                            
                            p_data["storage"][r_type] -= actual_moved
                            transferred_totals[r_type] += actual_moved

            cd = calc_cd_4_1(stats.get("physique", 1))
            user_data["work_cooldown"] = int(time.time()) + cd
            user_data.setdefault("worked_today", {})["physique"] = True
            user_data["worked_today"]["agility"] = True
            
            save_guild_json(guild_id, DATA_FILE, data)
            save_guild_json(guild_id, MONOPOLY_FILE, mono)
            
            res_str = ", ".join([f"{k}: {v}" for k, v in transferred_totals.items() if v > 0])
            if not res_str: res_str = "Нічого переносити або бракує місця."
            
            if comp_channel:
                await comp_channel.send(f"🚛 Логіст **{interaction.user.display_name}** завершив перевезення на **{prop['name']}**.\n💵 ЗП: `{salary_to_pay} AC` | 📦 Прибуло: {res_str}.")

            return await interaction.response.send_message(f"🚛 Спроба перенесення {int(transfer_pct*100)}% ресурсів.\nПрибуло на цей склад: {res_str}\nЗарплата: `{salary_to_pay} AC`.\n⏳ Наступна зміна <t:{int(time.time()) + cd}:R>", ephemeral=True)

        # ==========================================
        # 6. ОХОРОНЕЦЬ (Склад)
        # ==========================================
        elif prof == "охоронець" and prop["type"] == "склад":
            if comp_owner == "STATE_COMPANY":
                config = load_guild_json(guild_id, ECONOMY_CONFIG)
                if config.get("server_bank", 0) < salary_to_pay: return await interaction.response.send_message("У Казні немає грошей.", ephemeral=True)
                config["server_bank"] -= salary_to_pay
                save_guild_json(guild_id, ECONOMY_CONFIG, config)
            else:
                current_reserve = prop.get("reserve", 0)
                if current_reserve < salary_to_pay:
                    return await interaction.response.send_message(f"❌ Бюджет складу порожній! Роботодавець не поповнив резерв (Потрібно: {salary_to_pay} AC).", ephemeral=True)
                prop["reserve"] = current_reserve - salary_to_pay
                
            user_data["balance"] += salary_to_pay

            duration_secs = calc_buff_duration_2_6(stats.get("wisdom", 1))
            if "buffs" not in prop: prop["buffs"] = {}
            prop["buffs"]["security_expires"] = int(time.time()) + duration_secs

            cd = calc_cd_8_6(stats.get("physique", 1))
            user_data["work_cooldown"] = int(time.time()) + cd
            user_data.setdefault("worked_today", {})["physique"] = True
            user_data["worked_today"]["wisdom"] = True
            
            save_guild_json(guild_id, DATA_FILE, data)
            save_guild_json(guild_id, MONOPOLY_FILE, mono)
            
            hours = round(duration_secs / 3600, 1)
            
            if comp_channel:
                await comp_channel.send(f"🛡️ Охоронець **{interaction.user.display_name}** заступив на зміну на **{prop['name']}** (Захист на {hours} год).\n💵 ЗП: `{salary_to_pay} AC`.")

            return await interaction.response.send_message(f"🛡️ Склад під захистом на {hours} год!\nЗарплата: `{salary_to_pay} AC`.\n⏳ Наступна зміна <t:{int(time.time()) + cd}:R>", ephemeral=True)

        else:
            return await interaction.response.send_message("Невідома комбінація професії та нерухомості.", ephemeral=True)

    @app_commands.command(name="vacancies", description="Переглянути доступні вакансії на сервері")
    @app_commands.guild_only()
    async def vacancies(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        mono_data = get_monopoly_data(guild_id)
        
        vacancies_tree = {}
        for owner_id, comp in mono_data.get("companies", {}).items():
            for prop_id, prop in comp.get("properties", {}).items():
                if prop["durability"] == 0: continue 
                
                salaries = prop.get("salaries", {})
                limits = prop.get("vacancy_limits", {})
                available_profs = []
                
                for prof in PROFESSIONS.get(prop["type"], []):
                    current_prof_workers = sum(1 for p in prop.get("workers", {}).values() if p == prof)
                    prof_limit = limits.get(prof, 1)
                    if current_prof_workers < prof_limit:
                        available_profs.append(prof)
                        
                if available_profs:
                    if owner_id not in vacancies_tree: vacancies_tree[owner_id] = {}
                    vacancies_tree[owner_id][prop_id] = available_profs

        if not vacancies_tree:
            return await interaction.response.send_message("📉 Наразі на сервері немає жодної відкритої вакансії. Зайдіть пізніше!", ephemeral=True)

        embed = discord.Embed(title="📋 Біржа Праці", description=f"Знайдено компаній з відкритими вакансіями: **{len(vacancies_tree)}**\n*Оберіть компанію зі списку нижче, щоб розпочати.*", color=0x3498db)
        await interaction.response.send_message(embed=embed, view=JobNavView(self, vacancies_tree, mono_data), ephemeral=True)

    @app_commands.command(name="job_leave", description="Звільнитися з поточної роботи")
    @app_commands.guild_only()
    async def job_leave(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        data = load_guild_json(guild_id, DATA_FILE)
        mono_data = get_monopoly_data(guild_id)
        user_data = self.get_user(data, user_id)
        job_info = user_data.get("job", {})
        
        if not job_info: return await interaction.response.send_message("Ви ніде не працюєте.", ephemeral=True)
            
        comp_id = job_info.get("company_id")
        prop_id = job_info.get("prop_id")
        
        if comp_id in mono_data["companies"]:
            comp = mono_data["companies"][comp_id]
            if prop_id in comp["properties"]:
                prop = comp["properties"][prop_id]
                if user_id in prop.get("workers", {}):
                    del prop["workers"][user_id]
                    
            channel = interaction.guild.get_channel(comp["channel_id"])
            if channel:
                await channel.set_permissions(interaction.user, overwrite=None)
                await channel.send(f"🚪 Працівник {interaction.user.mention} звільнився за власним бажанням.")

        user_data["job"] = {}
        save_guild_json(guild_id, DATA_FILE, data)
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        
        await interaction.response.send_message("Ви успішно звільнилися. Тепер ви можете шукати нову роботу!", ephemeral=True)

    # ==========================================
    # КОМАНДИ УПРАВЛІННЯ ПЕРСОНАЛОМ
    # ==========================================

    @app_commands.command(name="company_workers", description="Список працівників вашої компанії")
    @app_commands.guild_only()
    async def company_workers(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        mono_data = get_monopoly_data(guild_id)
        
        if user_id not in mono_data["companies"]:
            return await interaction.response.send_message("У вас немає власної компанії.", ephemeral=True)
            
        comp = mono_data["companies"][user_id]
        embed = discord.Embed(title=f"👥 Штат працівників: {comp['name']}", color=0x3498db)
        
        has_workers = False
        for prop_id, prop in comp["properties"].items():
            workers = prop.get("workers", {})
            if workers:
                has_workers = True
                worker_lines = []
                for w_id, prof in workers.items():
                    salary = prop.get("salaries", {}).get(prof, 100)
                    worker_lines.append(f"• <@{w_id}> — **{prof.capitalize()}** (`{salary} AC`)")
                
                embed.add_field(
                    name=f"🏢 {prop['name']} ({prop['type'].capitalize()})",
                    value="\n".join(worker_lines),
                    inline=False
                )
                
        if not has_workers:
            embed.description = "У вашій компанії наразі немає жодного найманого працівника."
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="fire", description="Звільнити працівника з вашої компанії")
    @app_commands.describe(member="Кого звільняємо?", reason="Причина звільнення")
    @app_commands.guild_only()
    async def fire(self, interaction: discord.Interaction, member: discord.User, reason: str = "Рішення керівництва"):
        guild_id = interaction.guild.id
        owner_id = str(interaction.user.id)
        target_id = str(member.id)
        
        if owner_id == target_id:
            return await interaction.response.send_message("Ви не можете звільнити самого себе.", ephemeral=True)
            
        mono_data = get_monopoly_data(guild_id)
        users_data = load_guild_json(guild_id, DATA_FILE)
        
        if owner_id not in mono_data["companies"]:
            return await interaction.response.send_message("У вас немає компанії.", ephemeral=True)
            
        comp = mono_data["companies"][owner_id]
        target_prop = None
        
        for prop in comp["properties"].values():
            if target_id in prop.get("workers", {}):
                target_prop = prop
                break
                
        if not target_prop:
            return await interaction.response.send_message(f"Користувач {member.display_name} не працює у вашій компанії.", ephemeral=True)
            
        del target_prop["workers"][target_id]
        
        if target_id in users_data:
            users_data[target_id]["job"] = {}
            
        save_guild_json(guild_id, MONOPOLY_FILE, mono_data)
        save_guild_json(guild_id, DATA_FILE, users_data)
        
        channel_id = comp.get("channel_id")
        if channel_id:
            comp_channel = interaction.guild.get_channel(channel_id)
            if comp_channel:
                await comp_channel.set_permissions(member, overwrite=None)
                await comp_channel.send(f"Керівник звільнив працівника {member.mention}. Причина: {reason}")
                
        try:
            await member.send(f"Вас було звільнено з компанії **{comp['name']}**.\n**Причина:** {reason}")
        except:
            pass
            
        await interaction.response.send_message(f"Працівника {member.mention} успішно звільнено.", ephemeral=True)

    @app_commands.command(name="admin_reset_cd", description="[АДМІН] Примусово скинути КД роботи гравцю")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def admin_reset_cd(self, interaction: discord.Interaction, member: discord.User):
        guild_id = interaction.guild.id
        target_id = str(member.id)
        
        data = load_guild_json(guild_id, DATA_FILE)
        
        if target_id not in data:
            return await interaction.response.send_message(f"Гравця {member.mention} немає в базі даних.", ephemeral=True)
            
        user_data = self.get_user(data, target_id)
        user_data["work_cooldown"] = 0
        
        save_guild_json(guild_id, DATA_FILE, data)
        await interaction.response.send_message(f"Ви успішно скинули КД для роботи гравцю {member.mention}. Він може працювати прямо зараз!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(WorkCog(bot))