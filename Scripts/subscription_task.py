import os
import sqlite3
import time
import logging
import sys

import bookshelfAPI as c
import settings as s
from multi_user import search_user_db
from wishlist import search_wishlist_db, mark_book_as_downloaded

from interactions import *
from interactions.api.events import Startup
from datetime import datetime, timedelta
from interactions.ext.paginators import Paginator
from dotenv import load_dotenv

# Enable dot env outside of docker
load_dotenv()

# Logger Config
logger = logging.getLogger("bot")

# VARS
TASK_FREQUENCY = 5

# Create new relative path
db_path = 'db/tasks.db'
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Initialize sqlite3 connection

conn = sqlite3.connect(db_path)
cursor = conn.cursor()


async def conn_test():
    # Will print username when successful
    auth_test, user_type, user_locked = await c.bookshelf_auth_test()
    logger.info(f"Logging user in and verifying role.")

    # Quit if user is locked
    if user_locked:
        logger.warning("User locked from logging in, please unlock via web gui.")
        sys.exit("User locked from logging in, please unlock via web gui.")

    # Check if ABS user is an admin
    ADMIN_USER = False
    if user_type == "root" or user_type == "admin":
        ADMIN_USER = True
        logger.info(f"ABS user logged in as ADMIN with type: {user_type}")
    else:
        logger.info(f"ABS user logged in as NON-ADMIN with type: {user_type}")
    return ADMIN_USER


def tasks_table_create():
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            discord_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            task TEXT NOT NULL,
            server_name TEXT NOT NULL,
            token TEXT,
            UNIQUE(channel_id, task)
        )
    ''')

    # Check if 'token' column exists
    cursor.execute("PRAGMA table_info(tasks)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'token' not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN token TEXT")


def version_table_create():
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS version_control (
        id INTEGER PRIMARY KEY,
        version TEXT,
        UNIQUE(version)
)
    ''')
    conn.commit()


# Initialize table
logger.info("Initializing tasks table")
tasks_table_create()

logger.info("Initializing versions table")
version_table_create()


def insert_data(discord_id: int, channel_id: int, task, server_name, token):
    try:
        cursor.execute('''
        INSERT INTO tasks (discord_id, channel_id, task, server_name, token) VALUES (?, ?, ?, ?, ?)''',
                       (int(discord_id), int(channel_id), task, server_name, token))
        conn.commit()
        logger.info(f"Inserted: {discord_id} into tasks table!")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Failed to insert: {discord_id} with task {task} already exists.")
        return False


def insert_version(version):
    try:
        cursor.execute('''INSERT INTO version_control (version) VALUES (?)''', (version,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Failed to insert: {version} as it already exists.")
        return False


def search_version_db():
    cursor.execute('''
    SELECT id, version FROM version_control
    ''')
    rows = cursor.fetchall()
    return rows


def remove_task_db(task='', discord_id=0, db_id=0):
    logger.warning(f'Attempting to delete task {task} with discord id {discord_id} from db!')
    try:
        if task != '' and discord_id != 0:
            cursor.execute("DELETE FROM tasks WHERE task = ? AND discord_id = ?", (task, int(discord_id)))
            conn.commit()
            logger.info(f"Successfully deleted task {task} with discord id {discord_id} from db!")
            return True
        elif db_id != 0:
            cursor.execute("DELETE FROM tasks WHERE id = ?", (int(db_id),))
            conn.commit()
            logger.info(f"Successfully deleted task with id {db_id}")
            return True
    except sqlite3.Error as e:
        logger.error(f"Error while attempting to delete {task}: {e}")
        return False


def search_task_db(discord_id=0, task='', channel_id=0, override_response='') -> ():
    override = False

    if override_response != '':
        response = override_response
        logger.warning(response)
        override = True
    else:
        logger.info('Initializing sqlite db search for subscription task module.')

    if channel_id != 0 and task == '' and discord_id == 0:
        option = 1
        if not override:
            logger.info(f'OPTION {option}: Searching db using channel ID in tasks table.')
        cursor.execute('''
        SELECT discord_id, task FROM tasks WHERE channel_id = ?
        ''', (channel_id, task))
        rows = cursor.fetchall()

    elif discord_id != 0 and task != '' and channel_id == 0:
        option = 2
        if not override:
            logger.info(f'OPTION {option}: Searching db using discord ID and task name in tasks table.')
        cursor.execute('''
                SELECT channel_id, server_name FROM tasks WHERE discord_id = ? AND task = ?
                ''', (discord_id, task))
        rows = cursor.fetchone()

    elif discord_id != 0 and task == '' and channel_id == 0:
        option = 3
        if not override:
            logger.info(f'OPTION {option}: Searching db using discord ID in tasks table.')
        cursor.execute('''
                        SELECT task, channel_id, id, token FROM tasks WHERE discord_id = ?
                        ''', (discord_id,))
        rows = cursor.fetchall()

    elif task != '':
        option = 4
        if not override:
            logger.info(f'OPTION {option}: Searching db using task name in tasks table.')
        cursor.execute('''
                        SELECT task, channel_id, id, token FROM tasks WHERE task = ?
                        ''', (task,))
        rows = cursor.fetchall()

    else:
        option = 5
        if not override:
            logger.info(f'OPTION {option}: Searching db using no arguments in tasks table.')
        cursor.execute('''SELECT discord_id, task, channel_id, server_name FROM tasks''')
        rows = cursor.fetchall()

    if rows:
        if not override:
            logger.info(
                f'Successfully found query using option: {option} using table tasks in subscription task module.')
    else:
        if not override:
            logger.warning('Query returned null using table tasks, an error may follow.')

    return rows


async def newBookList(task_frequency=TASK_FREQUENCY) -> list:
    logger.debug("Initializing NewBookList function")
    items_added = []
    current_time = datetime.now()

    libraries = await c.bookshelf_libraries()

    library_count = len(libraries)

    logger.debug(f'Found {library_count} libraries')

    time_minus_delta = current_time - timedelta(minutes=task_frequency)
    timestamp_minus_delta = int(time.mktime(time_minus_delta.timetuple()) * 1000)

    for name, (library_id, audiobooks_only) in libraries.items():
        library_items = await c.bookshelf_all_library_items(library_id, params="sort=addedAt&desc=1")

        for item in library_items:
            latest_item_time_added = int(item.get('addedTime'))
            latest_item_title = item.get('title')
            latest_item_type = item.get('mediaType')
            latest_item_author = item.get('author')
            latest_item_bookID = item.get('id')
            try:
                latest_item_provider_id = item.get('asin')
            except Exception as e:
                latest_item_provider_id = ''
                logger.debug("Couldn't fetch asin from item. Likely was not set with metadata.")
                logger.debug(f"Error: {e}")

            if "(Abridged)" in latest_item_title:
                latest_item_title = latest_item_title.replace("(Abridged)", '').strip()
            if "(Unabridged)" in latest_item_title:
                latest_item_title = latest_item_title.replace("(Unabridged)", '').strip()

            formatted_time = latest_item_time_added / 1000
            formatted_time = datetime.fromtimestamp(formatted_time)
            formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

            if latest_item_time_added >= timestamp_minus_delta and latest_item_type == 'book':
                items_added.append({"title": latest_item_title, "addedTime": formatted_time,
                                    "author": latest_item_author, "id": latest_item_bookID,
                                    "provider_id": latest_item_provider_id})

        return items_added


class SubscriptionTask(Extension):
    def __init__(self, bot):
        # Channel object has 3 main properties .name, .id, .type
        self.TaskChannel = None
        self.TaskChannelID = None
        self.ServerNickName = ''
        self.embedColor = None
        self.admin_token = None
        self.previous_token = None
        self.bot.admin_token = None

    async def get_server_name_db(self, discord_id=0, task='new-book-check'):
        cursor.execute('''
                SELECT server_name FROM tasks WHERE discord_id = ? OR task = ?
                ''', (int(discord_id), task))
        rows = cursor.fetchone()
        if rows:
            for row in rows:
                logger.debug(f'Setting server nickname to {row}')
                self.ServerNickName = row
        return rows

    async def send_user_wishlist(self, discord_id: int, title: str, author: str, embed: list):
        user = await self.bot.fetch_user(discord_id)
        result = search_task_db(discord_id=discord_id, task='new-book-check')
        name = ''

        if result:
            try:
                name = result[1]
            except TypeError as error:
                logger.error(f"Couldn't assign server name, {error}")
                name = "Audiobookshelf"
        # Wishlist message
        msg = f"Hello **{user.display_name}**, one of your wishlisted books has become available! **{title}** by author **{author}** is now available on your Audiobookshelf server: **{name}**!"
        if len(embed) > 10:
            for emb in embed:

                await user.send(content=msg,
                                embed=emb)
        else:
            await user.send(content=msg,
                            embeds=embed)  # NOQA

    async def NewBookCheckEmbed(self, task_frequency=TASK_FREQUENCY, enable_notifications=False):  # NOQA
        bookshelfURL = os.getenv("bookshelfURL", "http://127.0.0.1")
        img_url = os.getenv('OPT_IMAGE_URL')

        if not self.ServerNickName:
            self.ServerNickName = "Audiobookshelf"

        items_added = await newBookList(task_frequency) or []

        if items_added:
            count = 0
            total_item_count = len(items_added)
            embeds = []
            wishlist_titles = []
            logger.info(f'{total_item_count} New books found, executing Task!')

            for item in items_added:
                count += 1
                title = item.get('title', 'Unknown Title')
                author = item.get('author', 'Unknown Author')
                addedTime = item.get('addedTime', 'Unknown Time')
                bookID = item.get('id', 'Unknown ID')

                logger.debug(f"Processing book: {title}")

                wishlisted = False
                cover_link = await c.bookshelf_cover_image(bookID) or "https://your-default-cover-url.com"

                wl_search = search_wishlist_db(title=title)
                if wl_search:
                    wishlisted = True
                    wishlist_titles.append(title)

                embed_message = Embed(
                    title=f"{title}",
                    description=f"Recently added book for [{self.ServerNickName}]({bookshelfURL})",
                    color=self.embedColor or FlatUIColors.ORANGE
                )

                embed_message.add_field(name="Title", value=title, inline=False)
                embed_message.add_field(name="Author", value=author)
                embed_message.add_field(name="Added Time", value=addedTime)
                embed_message.add_field(name="Additional Information", value=f"Wishlisted: **{wishlisted}**",
                                        inline=False)

                # Ensure URL is properly assigned
                if img_url and "https" in img_url:
                    bookshelfURL = img_url
                embed_message.url = f"{bookshelfURL}/item/{bookID}"

                embed_message.add_image(cover_link)
                embed_message.footer = f"{s.bookshelf_traveller_footer} | {self.ServerNickName}"

                embeds.append(embed_message)

                if wl_search:
                    for user in wl_search:
                        discord_id = user[0]
                        search_title = user[2]
                        if enable_notifications:
                            # Send notification and update database
                            await self.send_user_wishlist(discord_id=discord_id, title=title, author=author,
                                                          embed=embeds)
                            mark_book_as_downloaded(discord_id=discord_id, title=search_title)

            return embeds

    @staticmethod
    async def getFinishedBooks():
        current_time = datetime.now()
        book_list = []
        try:
            books = await c.bookshelf_get_valid_books()
            users = await c.get_users()

            time_minus_delta = current_time - timedelta(minutes=TASK_FREQUENCY)
            timestamp_minus_delta = int(time.mktime(time_minus_delta.timetuple()) * 1000)

            count = 0
            if users and books:

                for user in users['users']:
                    user_id = user.get('id')
                    username = user.get('username')

                    endpoint = f'/users/{user_id}'
                    r = await c.bookshelf_conn(endpoint=endpoint, GET=True)
                    if r.status_code == 200:
                        user_data = r.json()

                        for media in user_data['mediaProgress']:

                            media_type = media['mediaItemType']
                            libraryItemId = media['libraryItemId']
                            displayTitle = media.get('displayTitle')
                            finished = bool(media.get('isFinished'))

                            # Verify it's a book and not a podcast and the book is finished
                            if media_type == 'book' and finished:

                                finishedAtTime = int(media.get('finishedAt'))

                                # Convert time to regular format
                                formatted_time = finishedAtTime / 1000
                                formatted_time = datetime.fromtimestamp(formatted_time)
                                formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

                                if finishedAtTime >= timestamp_minus_delta:
                                    count += 1
                                    media['username'] = username
                                    book_list.append(media)
                                    logger.info(
                                        f'User {username}, finished Book: {displayTitle} with  ID: {libraryItemId} at {formatted_time}')

                logger.info(f"Total Found Books: {count}")

        except Exception as e:
            logger.error(f"Error occured while attempting to get finished book: {e}")

        return book_list

    async def FinishedBookEmbeds(self, book_list: list):
        count = 0
        embeds = []
        serverURL = os.getenv("bookshelfURL", "http://127.0.0.1")
        img_url = os.getenv('OPT_IMAGE_URL')
        for book in book_list:
            count += 1
            title = book.get('displayTitle', 'No Title Provided')
            bookID = book.get('libraryItemId')
            finishedAtTime = int(book.get('finishedAt'))
            username = book.get('username')

            # Get cover link
            cover_link = await c.bookshelf_cover_image(bookID)

            # Convert time to regular format
            formatted_time = finishedAtTime / 1000
            formatted_time = datetime.fromtimestamp(formatted_time)
            formatted_time = formatted_time.strftime('%Y/%m/%d %H:%M')

            # Construct embed message
            embed_message = Embed(
                title=f"{count}. Recently Finished Book | {title}",
                description=f"Recently finished books for [{self.ServerNickName}]({serverURL})",
                color=self.embedColor or FlatUIColors.ORANGE
            )

            embed_message.add_field(name="Title", value=title, inline=False)
            embed_message.add_field(name="Finished Time", value=formatted_time)
            embed_message.add_field(name="Finished by User", value=username,
                                    inline=False)

            # Ensure URL is properly assigned
            if img_url and "https" in img_url:
                serverURL = img_url
            embed_message.url = f"{serverURL}/item/{bookID}"

            embed_message.add_image(cover_link)
            embed_message.footer = f"{s.bookshelf_traveller_footer} | {self.ServerNickName}"

            embeds.append(embed_message)

        return embeds

    @staticmethod
    async def embed_color_selector(color=0):
        color = int(color)
        selected_color = FlatUIColors.CARROT
        # Yellow
        if color == 1:
            selected_color = FlatUIColors.SUNFLOWER
        # Orange
        elif color == 2:
            selected_color = FlatUIColors.CARROT
        # Purple
        elif color == 3:
            selected_color = FlatUIColors.AMETHYST
        # Turquoise
        elif color == 4:
            selected_color = FlatUIColors.TURQUOISE
        # Red
        elif color == 5:
            selected_color = FlatUIColors.ALIZARIN
        # Green
        elif color == 6:
            selected_color = FlatUIColors.EMERLAND

        return selected_color

    @Task.create(trigger=IntervalTrigger(minutes=TASK_FREQUENCY))
    async def newBookTask(self):
        logger.info("Initializing new-book-check task!")
        search_result = search_task_db(task='new-book-check')
        if search_result:
            if self.ServerNickName == '':
                await self.get_server_name_db()
            logger.debug(f"search result: {search_result}")

            self.previous_token = os.getenv('bookshelfToken')

            for result in search_result:
                channel_id = int(result[1])

                self.admin_token = result[3]
                masked = len(self.admin_token)
                logger.info(f"Appending Active Token! {masked}")
                os.environ['bookshelfToken'] = self.admin_token

                new_titles = await newBookList()
                if new_titles:
                    logger.debug(f"New Titles Found: {new_titles}")
                else:
                    logger.info("No new books found, marking task as complete.")
                    return

                if len(new_titles) > 10:
                    logger.warning("Found more than 10 titles")

                embeds = await self.NewBookCheckEmbed(enable_notifications=True)
                if embeds:

                    channel_query = await self.bot.fetch_channel(channel_id=channel_id, force=True)
                    if channel_query:
                        logger.debug(f"Found Channel: {channel_id}")
                        logger.debug(f"Bot will now attempt to send a message to channel id: {channel_id}")

                        if len(embeds) < 10:
                            msg = await channel_query.send(content="New books have been added to your library!")
                            await msg.edit(embeds=embeds)
                        else:
                            await channel_query.send(content="New books have been added to your library!")
                            for embed in embeds:
                                await channel_query.send(embed=embed)

                            # Reset admin token
                            self.admin_token = None

                # Reset Vars
                os.environ['bookshelfToken'] = self.previous_token
                print(f'Returned Active Token to: {self.previous_token}')
                self.previous_token = None
                logger.info("Successfully completed new-book-check task!")

        # If active but no result, disable task and send owner message.
        else:
            logger.warning("Task 'new-book-check' was active, but setup check failed.")
            self.newBookTask.stop()

    @Task.create(trigger=IntervalTrigger(minutes=TASK_FREQUENCY))
    async def finishedBookTask(self):
        logger.info('Initializing Finished Book Task!')
        search_result = search_task_db(task='finished-book-check')

        if search_result:
            self.previous_token = os.getenv('bookshelfToken')

            for result in search_result:
                channel_id = int(result[1])
                logger.info(f'Channel ID: {channel_id}')
                self.admin_token = result[3]
                masked = len(self.admin_token)
                logger.info(f"Appending Active Token! {masked}")
                os.environ['bookshelfToken'] = self.admin_token

                # Any Bookshelf Related Calls Need to be made below
                book_list = await self.getFinishedBooks()
                if book_list:
                    logger.info('Finished books found! Creating embeds.')
                else:
                    logger.info('No finished books found! Aborting!')
                    return

                embeds = await self.FinishedBookEmbeds(book_list)
                if embeds:

                    channel_query = await self.bot.fetch_channel(channel_id=channel_id, force=True)
                    if channel_query:
                        logger.debug(f"Found Channel: {channel_id}")
                        logger.debug(f"Bot will now attempt to send a message to channel id: {channel_id}")

                        if len(embeds) < 10:
                            msg = await channel_query.send(
                                content="These books have been recently finished in your library!")
                            await msg.edit(embeds=embeds)
                        else:
                            await channel_query.send(
                                content="These books have been recently finished in your library!")
                            for embed in embeds:
                                await channel_query.send(embed=embed)

                    # Reset admin token
                    self.admin_token = None

                    # Reset Vars
                    os.environ['bookshelfToken'] = self.previous_token
                    print(f'Returned Active Token to: {self.previous_token}')
                    self.previous_token = None
                    logger.info("Successfully completed finished-book-check task!")

        else:
            logger.warning("Task 'new-book-check' was active, but setup check failed.")
            self.finishedBookTask.stop()

    # Slash Commands ----------------------------------------------------

    @slash_command(name="new-book-check",
                   description="Verify if a new book has been added to your library. Can be setup as a task.",
                   dm_permission=True)
    @slash_option(name="minutes", description=f"Lookback period, in minutes. "
                                              f"Defaults to {TASK_FREQUENCY} minutes. DOES NOT AFFECT TASK.",
                  opt_type=OptionType.INTEGER)
    @slash_option(name="color", description="Will override the new book check embed color.", opt_type=OptionType.STRING,
                  autocomplete=True)
    @slash_option(name="enable_task", description="If set to true will enable recurring task.",
                  opt_type=OptionType.BOOLEAN)
    @slash_option(name="disable_task", description="If set to true, this will disable the task.",
                  opt_type=OptionType.BOOLEAN)
    async def newBookCheck(self, ctx: InteractionContext, minutes=TASK_FREQUENCY, enable_task=False,
                           disable_task=False, color=None):
        if color and minutes == TASK_FREQUENCY:
            self.embedColor = await self.embed_color_selector(color)
            await ctx.send("Successfully updated color!", ephemeral=True)
            return
        if enable_task and not disable_task:
            logger.info('Activating New Book Task! A message will follow.')
            if not self.newBookTask.running:
                operationSuccess = False
                search_result = search_task_db(ctx.author_id, task='new-book-check')
                if search_result:
                    print(search_result)
                    operationSuccess = True

                if operationSuccess:
                    if color:
                        self.embedColor = await self.embed_color_selector(color)

                    await ctx.send(
                        f"Activating New Book Task! This task will automatically refresh every *{TASK_FREQUENCY} minutes*!",
                        ephemeral=True)

                    self.newBookTask.start()
                    return
                else:
                    await ctx.send("Error activating new book task. Please visit logs for more information. "
                                   "Please make sure to setup the task prior to activation by using command **/setup-tasks**",
                                   ephemeral=True)
                    return
            else:
                logger.warning('New book check task was already running, ignoring...')
                await ctx.send('New book check task is already running, ignoring...', ephemeral=True)
                return
        elif disable_task and not enable_task:
            if self.newBookTask.running:
                if color:
                    self.embedColor = await self.embed_color_selector(color)
                await ctx.send("Disabled Task: *Recently Added Books*", ephemeral=True)
                self.newBookTask.stop()
                return
            else:
                pass
        elif disable_task and enable_task:
            await ctx.send(
                "Invalid option entered, please ensure only one option is entered from this command at a time.")
            return
        # Set server nickname
        await self.get_server_name_db(discord_id=ctx.author_id)

        await ctx.send(f'Searching for recently added books in given period of {minutes} minutes.', ephemeral=True)
        if color:
            self.embedColor = await self.embed_color_selector(color)
        embeds = await self.NewBookCheckEmbed(task_frequency=minutes, enable_notifications=False)
        if embeds:
            logger.info(f'Recent books found in given search period of {minutes} minutes!')
            paginator = Paginator.create_from_embeds(self.bot, *embeds)
            await paginator.send(ctx, ephemeral=True)
        else:
            await ctx.send(f"No recent books found in given search period of {minutes} minutes.",
                           ephemeral=True)
            logger.info(f'No recent books found.')

    @check(is_owner())
    @slash_command(name='setup-tasks', description="Setup a task", dm_permission=False)
    @slash_option(name='task', description='The task you wish to setup', required=True, autocomplete=True,
                  opt_type=OptionType.STRING)
    @slash_option(opt_type=OptionType.CHANNEL, name="channel", description="select a channel",
                  channel_types=[ChannelType.GUILD_TEXT], required=True)
    @slash_option(name='user', description="Select a stored user for the task to be executed by.",
                  opt_type=OptionType.STRING, autocomplete=True, required=True)
    @slash_option(name="server_name",
                  description="Give your Audiobookshelf server a nickname. This will overwrite the previous name.",
                  opt_type=OptionType.STRING, required=True)
    @slash_option(name='color', description='Embed message optional accent color, overrides default author color.',
                  opt_type=OptionType.STRING)
    async def task_setup(self, ctx: SlashContext, task, channel, user, server_name, color=None):
        task_name = ""
        success = False
        task_instruction = ''
        task_num = int(task)
        user_result = search_user_db(user=user)
        token = user_result[0]

        match task_num:
            # New book check task
            case 1:
                task_name = 'new-book-check'
                task_command = '`/new-book-check disable_task: True`'
                task_instruction = f'Task is now active. To disable, use **{task_command}**'
                result = insert_data(discord_id=ctx.author_id, channel_id=channel.id, task=task_name,
                                     server_name=server_name, token=token)

                if result:
                    success = True
                    if not self.newBookTask.running:
                        self.newBookTask.start()
                        logger.info('Successfully subscribed to new-book-check!')

            # Finished book check task
            case 2:
                task_name = 'finished-book-check'
                task_command = '`/remove-task task:finished-book-check`'
                task_instruction = f'Task is now active. To disable, use **{task_command}**'
                result = insert_data(discord_id=ctx.author_id, channel_id=channel.id, task=task_name,
                                     server_name=server_name, token=token)

                if result:
                    success = True
                    if not self.finishedBookTask.running:
                        self.finishedBookTask.start()
                        logger.info('Successfully subscribed to finished-book-task!')

        if success:
            if color:
                self.embedColor = await self.embed_color_selector(int(color))
            await ctx.send(
                f"Successfully setup task **{task_name}** with channel **{channel.name}**. \nInstructions: {task_instruction}",
                ephemeral=True)

            await self.get_server_name_db(discord_id=ctx.author_id)
        else:
            await ctx.send(
                f"An error occurred while attempting to setup the task **{task_name}**. Most likely due to the task already being setup. "
                f"Please visit the logs for more information.", ephemeral=True)

    @check(is_owner())
    @slash_command(name='remove-task', description="Remove an active task from the task db.")
    @slash_option(name='task', description="Active tasks pulled from db. Autofill format: c1: task | c2: channel name.",
                  autocomplete=True, required=True,
                  opt_type=OptionType.STRING)
    async def remove_task_command(self, ctx: SlashContext, task):
        result = remove_task_db(db_id=task)
        if result:
            await ctx.send("Successfully removed task!", ephemeral=True)
        else:
            await ctx.send("Failed to remove task, please visit logs for additional details.", ephemeral=True)

    @slash_command(name="active-tasks", description="View active tasks related to you.")
    async def active_tasks_command(self, ctx: SlashContext):
        embeds = []
        success = False
        result = search_task_db()
        if result:
            for discord_id, task, channel_id, server_name in result:
                channel = await self.bot.fetch_channel(channel_id)
                discord_user = await self.bot.fetch_user(discord_id)
                if channel and discord_user:
                    success = True
                    response = f"Channel: **{channel.name}**\nDiscord User: **{discord_user}**"
                    embed_message = Embed(
                        title="Task",
                        description="All Currently Active Tasks. *Note: this will pull for all channels and users.*",
                        color=ctx.author.accent_color
                    )
                    embed_message.add_field(name="Name", value=task)
                    embed_message.add_field(name="Discord Related Information", value=response)
                    embed_message.footer = s.bookshelf_traveller_footer

                    embeds.append(embed_message)

            if success:
                paginator = Paginator.create_from_embeds(self.client, *embeds)
                await paginator.send(ctx, ephemeral=True)

        else:
            await ctx.send("No currently active tasks found.", ephemeral=True)

    # Autocomplete Functions ---------------------------------------------
    @task_setup.autocomplete('task')
    async def auto_com_task(self, ctx: AutocompleteContext):
        choices = [
            {"name": "new-book-check", "value": "1"},
            {"name": "finished-book-check", "value": "2"}
        ]
        await ctx.send(choices=choices)

    @remove_task_command.autocomplete('task')
    async def remove_task_auto_comp(self, ctx: AutocompleteContext):
        choices = []
        result = search_task_db(discord_id=ctx.author_id)
        if result:
            for task, channel_id, db_id, token in result:
                channel = await self.bot.fetch_channel(channel_id)
                if channel:
                    response = f"{task} | {channel.name}"
                    choices.append({"name": response, "value": db_id})
        await ctx.send(choices=choices)

    @task_setup.autocomplete('color')
    @newBookCheck.autocomplete('color')
    async def color_embed_bookcheck(self, ctx: AutocompleteContext):
        choices = []
        count = 0
        colors = ['Default', 'Yellow', 'Orange', 'Purple', 'Turquoise', 'Red', 'Green']

        for color in colors:
            choices.append({"name": color, "value": str(count)})
            count += 1

        await ctx.send(choices=choices)

    @task_setup.autocomplete('user')
    async def user_search_task(self, ctx: AutocompleteContext):
        choices = []
        users_ = []
        user_result = search_user_db()
        if user_result:
            for user in user_result:
                username = user[0]

                if username not in users_:
                    users_.append(username)
                    choices.append({'name': username, 'value': username})

        await ctx.send(choices=choices)

    # --------------------------------------

    # Auto Start Task if db is populated
    @listen()
    async def tasks_startup(self, event: Startup):
        init_msg = bool(os.getenv('INITIALIZED_MSG', False))
        # Check if new version
        version_result = search_version_db()
        version_list = [v[1] for v in version_result]
        print("Saved Versions: ", version_result)
        print("Current Version: ", s.versionNumber)
        if s.versionNumber not in version_list:
            logger.warning("New version detected! To ensure this module functions properly remove any existing tasks!")
            await event.bot.owner.send(
                f'New version detected! To ensure the task subscription module functions properly remove any existing tasks with command `/remove-task`! Current Version: **{s.versionNumber}**')
            insert_version(s.versionNumber)

        result = search_task_db(
            override_response="Initialized subscription task module, verifying if any tasks are enabled...")
        task_name = "new-book-check"
        task_list = []
        if result:
            logger.info('Subscription Task db was populated, initializing tasks...')
            for item in result:
                task = item[1]
                task_list.append(task)

                logger.debug(f"Tasks db search result: {task}")

            # Check if new book check is running
            if not self.newBookTask.running and task_name in task_list:
                self.newBookTask.start()
                owner = event.bot.owner
                logger.info(
                    f"Enabling task: New Book Check on startup. Refresh rate set to {TASK_FREQUENCY} minutes.")
                # Debug Stuff
                if s.DEBUG_MODE and s.INITIALIZED_MSG:
                    await owner.send(
                        f"Subscription Task db was populated, auto enabling tasks on startup. Refresh rate set to {TASK_FREQUENCY} minutes.")

            if not self.finishedBookTask.running and 'finished-book-check' in task_list:
                self.finishedBookTask.start()
                logger.info(
                    f"Enabling task: Finished Book Check on startup. Refresh rate set to {TASK_FREQUENCY} minutes.")
