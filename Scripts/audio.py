import asyncio

import pytz
from interactions import *
from interactions.api.voice.audio import AudioVolume
import bookshelfAPI as c
import settings as s
from settings import DEBUG_MODE, TIMEZONE
import logging
from datetime import datetime
from dotenv import load_dotenv
import random

# Import UI component functions
from ui_components import (
    get_playback_rows,
    get_series_playback_rows,
    get_podcast_playback_rows,
    create_playback_embed
)

load_dotenv()

# Logger Config
logger = logging.getLogger("bot")

# Update Frequency for session sync
updateFrequency = s.UPDATES

# Default only owner can use this bot
ownership = s.OWNER_ONLY

# Timezone
timeZone = pytz.timezone(TIMEZONE)

# Custom check for ownership
async def ownership_check(ctx: BaseContext):  # NOQA

    logger.info(f'Ownership is currently set to: {ownership}')

    if ownership:
        logger.info('OWNERSHIP is enabled, verifying if user is authorized.')
        # Check to see if user is the owner while ownership var is true
        if ctx.bot.owner.id == ctx.user.id or ctx.user in ctx.bot.owners:
            logger.info('Verified, executing command!')
            return True
        else:
            logger.warning('User is not an owner!')
            return False

    else:
        logger.info('ownership is disabled! skipping!')
        return True


async def time_converter(time_sec: int) -> str:
    """
    :param time_sec:
    :return: a formatted string w/ time_sec + time_format(H,M,S)
    """
    formatted_time = time_sec
    playbackTimeState = 'Seconds'

    if time_sec >= 60 and time_sec < 3600:
        formatted_time = round(time_sec / 60, 2)
        playbackTimeState = 'Minutes'
    elif time_sec >= 3600:
        formatted_time = round(time_sec / 3600, 2)
        playbackTimeState = 'Hours'

    formatted_string = f"{formatted_time} {playbackTimeState}"

    return formatted_string


class AudioPlayBack(Extension):
    def __init__(self, bot):
        # ABS Vars
        self.cover_image = ''
        # Session VARS
        self.sessionID = ''
        self.bookItemID = ''
        self.bookTitle = ''
        self.bookDuration = None
        self.currentTime = 0.0
        self.activeSessions = 0
        self.sessionOwner = None
        # Chapter VARS
        self.currentChapter = None
        self.chapterArray = None
        self.currentChapterTitle = ''
        self.newChapterTitle = ''
        self.found_next_chapter = False
        self.bookFinished = False
        self.nextTime = None
        # Series VARS
        self.isSeries = False
        self.seriesID = None
        self.seriesBooks = None
        self.currentBookIndex = None
        self.isFirstBook = False
        self.isLastBook = False
        # Audio VARS
        self.audioObj = AudioVolume
        self.context_voice_channel = None
        self.current_playback_time = 0
        self.audio_context = None
        self.bitrate = 128000
        self.volume = 0.0
        self.placeholder = None
        self.playbackSpeed = 1.0
        self.isPodcast = False
        self.updateFreqMulti = updateFrequency * self.playbackSpeed
        self.play_state = 'stopped'
        self.audio_message = None
        # User Vars
        self.username = ''
        self.user_type = ''
        self.current_channel = None
        self.active_guild_id = None

    # Tasks ---------------------------------

    async def sync_playback_position(self, new_position, update_chapter_info=True):
        """Helper function to sync playback position with server and update local state"""
        if not self.sessionID:
            logger.warning("Cannot sync playback: No active session")
            return None, None, False

        try:
            # Set next time for sync
            self.nextTime = new_position

            # Close current session
            await c.bookshelf_close_session(self.sessionID)

            # Get new audio object with the updated position
            audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(self.bookItemID)

            if not sessionID:
                logger.error("Failed to get new session ID during sync")
                return None, None, False

            # Update session properties
            self.sessionID = sessionID
            self.bookDuration = bookDuration
        
            # Create new audio object
            audio = AudioVolume(audio_obj)
            audio.ffmpeg_before_args = f"-ss {new_position}"
            audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
            self.audioObj = audio

            # Send manual sync to set position immediately
            updated_time, duration, server_current_time, finished_book = await c.bookshelf_session_update(
                item_id=self.bookItemID, 
                session_id=self.sessionID,
                current_time=updateFrequency - 0.5, 
                next_time=self.nextTime
            )
    
            if updated_time is not None:
                self.currentTime = updated_time
    
            # Update chapter info if requested
            if update_chapter_info:
                try:
                    updated_chapter, chapter_array, book_finished, is_podcast = await c.bookshelf_get_current_chapter(
                        item_id=self.bookItemID, current_time=self.currentTime)
            
                    if updated_chapter:
                        self.currentChapter = updated_chapter
                        self.currentChapterTitle = updated_chapter.get('title', 'Unknown Chapter')
                        self.chapterArray = chapter_array
                        logger.info(f"Updated current chapter to: {self.currentChapterTitle}")
                except Exception as e:
                    logger.error(f"Error updating chapter info: {e}")
    
            # Reset nextTime after sync
            self.nextTime = None
    
            return updated_time, duration, finished_book

        except Exception as e:
            logger.error(f"Error in sync_playback_position: {e}")
            return None, None, False

    async def update_playback_message(self, ctx, edit_origin=False):
        """Helper function to update the playback message UI based on current state"""
        try:
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
        
            if self.isSeries:
                components = get_series_playback_rows(
                    "paused" if self.play_state == 'paused' else "playing",
                    self.isFirstBook,
                    self.isLastBook
                )
            else:
                components = get_playback_rows("paused" if self.play_state == 'paused' else "playing")
        
            if edit_origin:
                await ctx.edit_origin(embed=embed_message, components=components)
            elif self.audio_message:
                await self.audio_message.edit(embed=embed_message, components=components)
        except Exception as e:
            logger.error(f"Error updating playback message: {e}")

    @Task.create(trigger=IntervalTrigger(seconds=updateFrequency))
    async def session_update(self):
        logger.debug(f"Session sync, refresh rate: {updateFrequency} seconds") if DEBUG_MODE else None

        try:
            self.current_playback_time = self.current_playback_time + updateFrequency

            # Try to update the session
            try:
                updatedTime, duration, serverCurrentTime, finished_book = await c.bookshelf_session_update(
                    item_id=self.bookItemID,
                    session_id=self.sessionID,
                    current_time=updateFrequency,
                    next_time=None)  # Pass None instead of self.nextTime

                self.currentTime = updatedTime
                logger.debug(f"Session synced to time: {updatedTime} | session ID: {self.sessionID}") if DEBUG_MODE else None

                # Check if book is finished
                if finished_book:
                    logger.info("Book playback has finished based on session update")
                    # Check if book is part of a series
                    if self.isSeries and not self.isLastBook:
                        logger.info("Book is part of a series and not the last book. Could offer to play next book.")
                        # Could trigger auto-next-book or show notification

            except TypeError as e:
                logger.warning(f"Session update error: {e} - session may be invalid or closed")
                # Continue with task to allow chapter update even if session update fails

            # Try to get current chapter
            try:
                current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(
                    self.bookItemID, updatedTime if 'updatedTime' in locals() else None)

                if not isPodcast and current_chapter:
                    # Check if current_chapter has a title key
                    chapter_title = current_chapter.get('title', 'Unknown Chapter')
                    logger.info(f"Current Chapter Sync: {chapter_title}")
                    self.currentChapter = current_chapter
                    if self.currentChapterTitle != chapter_title:
                        logger.info(f"Chapter changed: {chapter_title}")
                        self.currentChapter = current_chapter
                        self.currentChapterTitle = chapter_title
                
            except Exception as e:
                logger.warning(f"Error getting current chapter: {e}")

        except Exception as e:
            logger.error(f"Unhandled error in session_update task: {e}")
            # Don't stop the task on errors, let it continue for the next interval

    @Task.create(trigger=IntervalTrigger(minutes=4))
    async def auto_kill_session(self):
        if self.play_state == 'paused' and self.audio_message is not None:
            logger.warning("Auto kill session task active! Playback was paused, verifying if session should be active.")
            voice_state = self.bot.get_bot_voice_state(self.active_guild_id)
            channel = await self.bot.fetch_channel(self.current_channel)

            chan_msg = await channel.send(
                f"Current playback of **{self.bookTitle}** will be stopped in **60 seconds** if no activity occurs.")
            await asyncio.sleep(60)

            if channel and voice_state and self.play_state == 'paused':
                await chan_msg.edit(
                    content=f'Current playback of **{self.bookTitle}** has been stopped due to inactivity.')
                await voice_state.stop()
                await voice_state.disconnect()
                await c.bookshelf_close_session(self.sessionID)
                logger.warning("audio session deleted due to timeout.")

                # Reset Vars and close out loops
                self.current_channel = None
                self.play_state = 'stopped'
                self.audio_message = None
                self.activeSessions -= 1
                self.sessionOwner = None
                self.audioObj.cleanup()  # NOQA

                if self.session_update.running:
                    self.session_update.stop()

            else:
                logger.debug("Session resumed, aborting task and deleting message!")
                await chan_msg.delete()

            # End loop
            self.auto_kill_session.stop()

        # elif self.play_state == 'playing':
        #     logger.info('Verifying if session should be active')
        #     if self.current_channel is not None:
        #         channel = self.bot.fetch_channel(self.current_channel)

    # Random Functions ------------------------
    # Change Chapter Function
    async def move_chapter(self, option: str):
        logger.info(f"executing command /next-chapter")
        CurrentChapter = self.currentChapter
        ChapterArray = self.chapterArray
        bookFinished = self.bookFinished

        if not self.currentChapter or not self.chapterArray:
            logger.warning("Cannot move chapter: Missing chapter information")
            return False

        if not bookFinished:
            currentChapterID = int(CurrentChapter.get('id'))
            if option == 'next':
                nextChapterID = currentChapterID + 1
            else:
                nextChapterID = currentChapterID - 1

            # Check if we're going below Chapter 1 (index 0)
            if nextChapterID < 0 and option == 'previous':
                logger.info("Attempting to go before Chapter 1, will restart the book instead")
                # Just use the first chapter (index 0)
                nextChapterID = 0

            for chapter in ChapterArray:
                chapterID = int(chapter.get('id'))

                if nextChapterID == chapterID:
                    self.session_update.stop()
                    # Close current session
                    await c.bookshelf_close_session(self.sessionID)

                    # Get chapter start position
                    chapterStart = float(chapter.get('start'))
                    self.newChapterTitle = chapter.get('title')

                    logger.info(f"Selected Chapter: {self.newChapterTitle}, Starting at: {chapterStart}")

                    # Get new audio object
                    audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(self.bookItemID)

                    self.sessionID = sessionID
                    self.bookDuration = bookDuration

                    self.currentChapter = chapter
                    self.currentChapterTitle = chapter.get('title')
                    logger.info(f"Updated current chapter to: {self.currentChapterTitle}")

                    audio = AudioVolume(audio_obj)
                    audio.ffmpeg_before_args = f"-ss {chapterStart}"
                    audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
                    self.audioObj = audio

                    # Update position using sync method
                    await self.sync_playback_position(chapterStart)

                    # Reset currentTime with the value from sync_playback_position
                    self.currentTime = chapterStart  # This might be redundant now that sync_playback_position updates currentTime

                    try:
                        verified_chapter, _, _, _ = await c.bookshelf_get_current_chapter(
                            item_id=self.bookItemID, current_time=chapterStart)
                    
                        if verified_chapter:
                            verified_title = verified_chapter.get('title')
                            logger.info(f"Server verified chapter title: {verified_title}")
                        
                            # If there's a mismatch, update to the server's version
                            if verified_title != self.currentChapterTitle:
                                logger.warning(f"Chapter title mismatch! Local: {self.currentChapterTitle}, Server: {verified_title}")
                                self.currentChapter = verified_chapter
                                self.currentChapterTitle = verified_title
                    except Exception as e:
                        logger.error(f"Error verifying chapter info: {e}")

                    self.session_update.start()

                    self.found_next_chapter = True
                    return

    def modified_message(self, color, chapter):
        now = datetime.now(tz=timeZone)
        formatted_time = now.strftime("%m-%d %H:%M:%S")

        # Calculate progress percentage and time progressed
        progress_percentage = 0
        if self.bookDuration and self.bookDuration > 0:
            safe_current_time = min(self.currentTime, self.bookDuration)
            progress_percentage = (safe_current_time / self.bookDuration) * 100
            progress_percentage = round(progress_percentage, 1)
            progress_percentage = max(0, min(100, progress_percentage))

        duration = self.bookDuration
        TimeState = 'Seconds'
        _time = duration
        if self.bookDuration >= 60 and self.bookDuration < 3600:
            _time = round(duration / 60, 2)
            TimeState = 'Minutes'
        elif self.bookDuration >= 3600:
            _time = round(duration / 3600, 2)
            TimeState = 'Hours'

        formatted_duration = f"{_time} {TimeState}"
        formatted_current = f"{round(self.currentTime / 60, 2)} Minutes"

        return create_playback_embed(
            book_title=self.bookTitle,
            chapter_title=chapter,
            progress=f"{progress_percentage}%",
            current_time=formatted_current,
            duration=formatted_duration,
            username=self.username,
            user_type=self.user_type,
            cover_image=self.cover_image,
            color=color,
            volume=self.volume,
            timestamp=formatted_time,
            version=s.versionNumber
        )

    # Commands --------------------------------

    # Main play command, place class variables here since this is required to play audio
    @slash_command(name="play", description="Play audio from ABS server", dm_permission=False)
    @slash_option(name="book", description="Enter a book title or 'random' for a surprise", required=True,
                  opt_type=OptionType.STRING,
                  autocomplete=True)
    @slash_option(name="startover",
                  description="Start the book from the beginning instead of resuming",
                  opt_type=OptionType.BOOLEAN)
    async def play_audio(self, ctx: SlashContext, book: str, startover=False):
        # Check for ownership if enabled
        if ownership:
            if ctx.author.id not in ctx.bot.owners:
                logger.warning(f'User {ctx.author} attempted to use /play, and OWNER_ONLY is enabled!')
                await ctx.send(
                    content="Ownership enabled and you are not authorized to use this command. Contact bot owner.")
                return

        if not self.bot.is_ready or not ctx.author.voice:
            await ctx.send(content="Bot is not ready or author not in voice channel, please try again later.",
                           ephemeral=True)
            return

        logger.info(f"executing command /play")

        # Defer the response right away to prevent "interaction already responded to" errors
        await ctx.defer(ephemeral=True)

        # Handle 'random' book selection here
        random_selected = False
        random_book_title = None
        if book.lower() == 'random':
            logger.info('Random book option selected, selecting a surprise book!')
            try:
                titles_ = await c.bookshelf_get_valid_books()
                titles_count = len(titles_)
                logger.info(f"Total Title Count: {titles_count}")

                if titles_count == 0:
                    await ctx.send(content="No books found in your library to play randomly.", ephemeral=True)
                    return

                random_title_index = random.randint(0, titles_count - 1)
                random_book = titles_[random_title_index]
                random_book_title = random_book.get('title')
                book = random_book.get('id')
                random_selected = True

                logger.info(f'Surprise! {random_book_title} has been selected to play')
            except Exception as e:
                logger.error(f"Error selecting random book: {e}")
                await ctx.send(content="Error selecting a random book. Please try again.", ephemeral=True)
                return

        try:
            book_details = await c.bookshelf_get_item_details(book)
            logger.debug(f"Retrieved book details for {book}")
    
            # Initialize series variables to defaults
            self.isSeries = False
            self.seriesID = None
            self.seriesBooks = None
            self.currentBookIndex = None
            self.isFirstBook = False
            self.isLastBook = False

            if book_details and 'series' in book_details and book_details['series']:
                # Book is part of a series
                self.isSeries = True
                series_name = book_details['series'].split(',')[0].strip() if ',' in book_details['series'] else book_details['series']
                series_sequence = book_details['series'].split('Book')[1].strip() if 'Book' in book_details['series'] else '0'

                logger.info(f"Book is part of series: {series_name}, Book {series_sequence}")

                # Set initial series flags
                self.isFirstBook = series_sequence == '1'
                self.isLastBook = False
            else:
                # Reset series flags for non-series books
                self.isSeries = False
                self.seriesID = None
                self.seriesBooks = None
                self.currentBookIndex = None
                self.isFirstBook = False
                self.isLastBook = False
        except Exception as e:
            logger.warning(f"Error checking series info: {e}")
            # Reset series flags on error
            self.isSeries = False
            self.seriesID = None
            self.seriesBooks = None
            self.currentBookIndex = None
            self.isFirstBook = False
            self.isLastBook = False

            # Proceed with the normal playback flow using the book ID
            current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(item_id=book)

            if current_chapter is None:
                await ctx.send(content="Error retrieving chapter information. The item may be invalid or inaccessible.", ephemeral=True)
                return

            if isPodcast:
                await ctx.send(content="The content you attempted to play is currently not supported, aborting.",
                              ephemeral=True)
                return

            if bookFinished and not startover:
                await ctx.send(content="This book is marked as finished. Use the `startover: True` option to play it from the beginning.", ephemeral=True)
                return

            if self.activeSessions >= 1:
                await ctx.send(content=f"Bot can only play one session at a time, please stop your other active session and try again! Current session owner: {self.sessionOwner}", ephemeral=True)
                return

            # Get Bookshelf Playback URI, Starts new session
            audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(book)

            if startover:
                logger.info(f"startover flag is true, setting currentTime to 0 instead of {currentTime}")
                currentTime = 0
                # Also find the first chapter
                if chapter_array and len(chapter_array) > 0:
                    # Sort chapters by start time
                    chapter_array.sort(key=lambda x: float(x.get('start', 0)))
                    first_chapter = chapter_array[0]
                    self.currentChapter = first_chapter
                    self.currentChapterTitle = first_chapter.get('title', 'Chapter 1')
                    logger.info(f"Setting to first chapter: {self.currentChapterTitle}")

            # Get Book Cover URL
            cover_image = await c.bookshelf_cover_image(book)

            # Retrieve current user information
            username, user_type, user_locked = await c.bookshelf_auth_test()

            # Audio Object Arguments
            audio = AudioVolume(audio_obj)
            audio.buffer_seconds = 5
            audio.locked_stream = True
            self.volume = audio.volume
            audio.ffmpeg_before_args = f"-ss {currentTime}"
            audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
            audio.bitrate = self.bitrate

            # Class VARS

            # ABS User Vars
            self.username = username
            self.user_type = user_type
            self.cover_image = cover_image

            # Session Vars
            self.sessionID = sessionID
            self.sessionOwner = ctx.author.username
            self.bookItemID = book
            self.bookTitle = bookTitle
            self.audioObj = audio
            self.currentTime = currentTime
            self.current_playback_time = 0
            self.audio_context = ctx
            self.active_guild_id = ctx.guild_id
            self.bookDuration = bookDuration

            # Chapter Vars
            self.isPodcast = isPodcast
            self.currentChapter = current_chapter if not startover else self.currentChapter  # Use first chapter if startover
            self.currentChapterTitle = current_chapter.get('title') if not startover else self.currentChapterTitle
            self.chapterArray = chapter_array
            self.bookFinished = bookFinished
            self.current_channel = ctx.channel_id
            self.play_state = 'playing'

            # Series VARS
            self.isSeries = False
            self.seriesID = None
            self.seriesBooks = None
            self.currentBookIndex = None
            self.isFirstBook = False
            self.isLastBook = False

            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            # check if bot currently connected to voice
            if not ctx.voice_state:
                # if we haven't already joined a voice channel
                try:
                    # Connect to voice channel and start task
                    await ctx.author.voice.channel.connect()
                    self.session_update.start()

                    # Customize message based on whether we're using random and/or startover
                    start_message = "Beginning audio stream"
                    if random_selected:
                        start_message = f"🎲 Randomly selected: **{random_book_title}**\n{start_message}"
                    if startover:
                        start_message += " from the beginning!"
                    else:
                        start_message += "!"

                    # Stop auto kill session task
                    if self.auto_kill_session.running:
                        self.auto_kill_session.stop()

                    # Use series UI if appropriate
                    if self.isSeries:
                        self.audio_message = await ctx.send(
                            content=start_message,
                            embed=embed_message,
                            components=get_series_playback_rows("playing", self.isFirstBook, self.isLastBook)
                        )
                    else:
                        self.audio_message = await ctx.send(
                            content=start_message,
                            embed=embed_message,
                            components=get_playback_rows("playing")
                        )

                    logger.info(f"Beginning audio stream" + (" from the beginning" if startover else ""))

                    self.activeSessions += 1

                    await self.client.change_presence(activity=Activity.create(name=f"{self.bookTitle}",
                                                                               type=ActivityType.LISTENING))

                    # Start audio playback
                    await ctx.voice_state.play(audio)

                except Exception as e:
                    # Stop Any Associated Tasks
                    if self.session_update.running:
                        self.session_update.stop()
                    # Close ABS session
                    await c.bookshelf_close_session(sessionID)  # NOQA
                    # Cleanup discord interactions
                    if ctx.voice_state:
                        await ctx.author.voice.channel.disconnect()
                    if audio:
                        audio.cleanup()  # NOQA

                    logger.error(f"Error starting playback: {e}")
                    await ctx.send(content=f"Error starting playback: {str(e)}")

        except Exception as e:
            logger.error(f"Unhandled error in play_audio: {e}")
            await ctx.send(content=f"An error occurred while trying to play this content: {str(e)}", ephemeral=True)

    # Pause audio, stops tasks, keeps session active.
    @slash_command(name="pause", description="pause audio", dm_permission=False)
    async def pause_audio(self, ctx):
        if ctx.voice_state:
            await ctx.send("Pausing Audio", ephemeral=True)
            logger.info(f"executing command /pause")
            ctx.voice_state.pause()
            logger.info("Pausing Audio")
            self.play_state = 'paused'
            # Stop Any Tasks Running and start autokill task
            if self.session_update.running:
                self.session_update.stop()
            self.auto_kill_session.start()
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    # Resume Audio, restarts tasks, session is kept open
    @slash_command(name="resume", description="resume audio", dm_permission=False)
    async def resume_audio(self, ctx):
        if ctx.voice_state:
            if self.sessionID != "":
                await ctx.send("Resuming Audio", ephemeral=True)
                logger.info(f"executing command /resume")
                # Resume Audio Stream
                ctx.voice_state.resume()
                logger.info("Resuming Audio")
                # Stop auto kill session task and start session
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()
                self.play_state = 'playing'
                self.session_update.start()
            else:
                await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @check(ownership_check)
    @slash_command(name="change-chapter", description="play next chapter, if available.", dm_permission=False)
    @slash_option(name="option", description="Select 'next or 'previous' as options", opt_type=OptionType.STRING,
                  autocomplete=True, required=True)
    async def change_chapter(self, ctx, option: str):
        if ctx.voice_state:
            if self.isPodcast:
                await ctx.send(content="Item type is not book, chapter skip disabled", ephemeral=True)
                return

            await self.move_chapter(option)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            await ctx.send(content=f"Moving to chapter: {self.newChapterTitle}", ephemeral=True)

            await ctx.voice_state.play(self.audioObj)

            if not self.found_next_chapter:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting",
                               ephemeral=True)
            # Resetting Variable
            self.found_next_chapter = False
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @check(ownership_check)
    @slash_command(name="volume", description="change the volume for the bot", dm_permission=False)
    @slash_option(name="volume", description="Must be between 1 and 100", required=False, opt_type=OptionType.INTEGER)
    async def volume_adjuster(self, ctx, volume=0):
        if ctx.voice_state:
            audio = self.audioObj
            if volume == 0:
                await ctx.send(content=f"Volume currently set to: {self.volume * 100}%", ephemaral=True)
            elif volume >= 1 < 100:
                volume_float = float(volume / 100)
                audio.volume = volume_float
                self.volume = audio.volume
                await ctx.send(content=f"Volume set to: {volume}%", ephemaral=True)

            else:
                await ctx.send(content=f"Invalid Entry", ephemeral=True)
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @slash_command(name="stop", description="Will disconnect from the voice channel and stop audio.",
                   dm_permission=False)
    async def stop_audio(self, ctx: SlashContext):
        if ctx.voice_state:
            logger.info(f"executing command /stop")
            await ctx.send(content="Disconnected from audio channel and stopping playback.", ephemeral=True)
            await ctx.voice_state.channel.voice_state.stop()
            await ctx.author.voice.channel.disconnect()
            self.audioObj.cleanup()  # NOQA
            await self.client.change_presence(activity=None)
            # Reset current playback time
            self.current_playback_time = 0
            self.activeSessions -= 1
            self.sessionOwner = None

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            if self.session_update.running:
                self.session_update.stop()
                # self.terminal_clearer.stop()
                self.play_state = 'stopped'
                await c.bookshelf_close_session(self.sessionID)
                await c.bookshelf_close_all_sessions(10)

        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)
            await c.bookshelf_close_all_sessions(10)

    @check(ownership_check)
    @slash_command(name="close-all-sessions",
                   description="DEBUGGING PURPOSES, close all active sessions. Takes up to 60 seconds.",
                   dm_permission=False)
    @slash_option(name="max_items", description="max number of items to attempt to close, default=100",
                  opt_type=OptionType.INTEGER)
    async def close_active_sessions(self, ctx, max_items=50):
        # Wait for task to complete
        ctx.defer()

        openSessionCount, closedSessionCount, failedSessionCount = await c.bookshelf_close_all_sessions(max_items)

        await ctx.send(content=f"Result of attempting to close sessions. success: {closedSessionCount}, "
                               f"failed: {failedSessionCount}, total: {openSessionCount}", ephemeral=True)

    @check(ownership_check)
    @slash_command(name='refresh', description='re-sends your current playback card.')
    async def refresh_play_card(self, ctx: SlashContext):
        if ctx.voice_state:
            try:
                current_chapter, chapter_array, bookFinished, isPodcast = await c.bookshelf_get_current_chapter(
                    self.bookItemID)
                self.currentChapterTitle = current_chapter.get('title')
            except Exception as e:
                logger.error(f"Error trying to fetch chapter title. {e}")

            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)
            if self.play_state == "playing":
                await ctx.send(embed=embed_message, components=get_playback_rows("playing"), ephemeral=True)
            elif self.play_state == "paused":
                await ctx.send(embed=embed_message, components=get_playback_rows("paused"), ephemeral=True)
        else:
            return await ctx.send("Bot not in voice channel or an error has occured. Please try again later!", ephemeral=True)

    # -----------------------------
    # Auto complete options below
    # -----------------------------
    @play_audio.autocomplete("book")
    async def search_media_auto_complete(self, ctx: AutocompleteContext):
        user_input = ctx.input_text
        choices = []
        logger.info(f"Autocomplete input: '{user_input}'")

        if user_input == "":
            try:
                # Add "Random" as the first option
                choices.append({"name": "📚 Random Book (Surprise me!)", "value": "random"})

                # Get recent sessions
                formatted_sessions_string, data = await c.bookshelf_listening_stats()
                valid_session_count = 0
                skipped_session_count = 0

                for session in data.get('recentSessions', []):
                    try:
                        # Get essential IDs
                        bookID = session.get('bookId')
                        itemID = session.get('libraryItemId')

                        # Skip sessions with missing essential data
                        if not itemID or not bookID:
                            logger.info(f"Skipping session with missing itemID or bookID")
                            skipped_session_count += 1
                            continue

                        # Extract metadata
                        mediaMetadata = session.get('mediaMetadata', {})
                        title = session.get('displayTitle')
                        subtitle = mediaMetadata.get('subtitle', '')
                        display_author = session.get('displayAuthor')

                        # Skip if both title and author are None (likely deleted item)
                        if title is None and display_author is None:
                            logger.info(f"Skipping session with no title or author for itemID: {itemID}")
                            skipped_session_count += 1
                            continue

                        # Log and handle None title case specifically
                        if title is None:
                            logger.info(f"Found session with None title for itemID: {itemID}, author: {display_author}")
                            title = 'Untitled Book'

                        # Apply default value for None author
                        if display_author is None:
                            logger.info(f"Found session with None author for itemID: {itemID}, title: {title}")
                            display_author = 'Unknown Author'

                        # Format name with smart truncation
                        name = f"{title} | {display_author}"
                        if len(name) > 100:
                            # First try title only
                            if len(title) <= 100:
                                name = title
                                logger.info(f"Truncated name to title only: {title}")
                            else:
                                # Try smart truncation with author
                                short_author = display_author[:20]
                                available_len = 100 - len(short_author) - 5  # Allow for "... | "
                                trimmed_title = title[:available_len] if available_len > 0 else "Untitled"
                                name = f"{trimmed_title}... | {short_author}"
                                logger.info(f"Smart truncated long title: {title} -> {trimmed_title}...")

                        # Ensure we don't exceed Discord limit
                        name = name.encode("utf-8")[:100].decode("utf-8", "ignore")

                        # Add to choices if not already there
                        formatted_item = {"name": name, "value": itemID}
                        if formatted_item not in choices:
                            choices.append(formatted_item)
                            valid_session_count += 1

                    except Exception as e:
                        logger.info(f"Error processing recent session: {e}")
                        skipped_session_count += 1
                        continue

                logger.info(f"Recent sessions processing complete - Valid: {valid_session_count}, Skipped: {skipped_session_count}")

                if not choices or len(choices) == 1:  # Only random option
                    logger.info("No valid recent sessions found, only showing random option")
                    choices = [{"name": "📚 Random Book (Surprise me!)", "value": "random"}]

                await ctx.send(choices=choices)

            except Exception as e:
                logger.error(f"Error retrieving recent sessions: {e}")
                choices = [{"name": "📚 Random Book (Surprise me!)", "value": "random"}]
                await ctx.send(choices=choices)

        else:
            # Handle user input search
            ctx.deferred = True
            try:
                # Add the random option if typing something that could be "random"
                if user_input == "random":
                    choices.append({"name": "📚 Random Book (Surprise me!)", "value": "random"})

                libraries = await c.bookshelf_libraries()
                valid_libraries = []
                found_titles = []

                # Get valid libraries
                for name, (library_id, audiobooks_only) in libraries.items():
                    valid_libraries.append({"id": library_id, "name": name})
                    logger.debug(f"Valid Library Found: {name} | {library_id}")

                # Search across all libraries, accumulating results
                for lib_id in valid_libraries:
                    library_iD = lib_id.get('id')
                    logger.debug(f"Searching library: {lib_id.get('name')} | {library_iD}")

                    try:
                        limit = 10
                        endpoint = f"/libraries/{library_iD}/search"
                        params = f"&q={user_input}&limit={limit}"
                        r = await c.bookshelf_conn(endpoint=endpoint, GET=True, params=params)

                        if r.status_code == 200:
                            data = r.json()
                            dataset = data.get('book', [])

                            for book in dataset:
                                authors_list = []
                                title = book['libraryItem']['media']['metadata']['title']
                                authors_raw = book['libraryItem']['media']['metadata']['authors']

                                for author in authors_raw:
                                    name = author.get('name')
                                    authors_list.append(name)

                                author = ', '.join(authors_list)
                                book_id = book['libraryItem']['id']

                                # Add to list if not already present (avoid duplicates)
                                new_item = {'id': book_id, 'title': title, 'author': author}
                                if not any(item['id'] == book_id for item in found_titles):
                                    found_titles.append(new_item)

                    except Exception as e:
                        logger.error(f"Error searching library {library_iD}: {e}")
                        continue  # Continue to next library even if this one fails

                # Process all found titles into choices for autocomplete
                for book in found_titles:
                    book_title = book.get('title', 'Unknown').strip()
                    author = book.get('author', 'Unknown').strip()
                    book_id = book.get('id')

                    if not book_id:
                        continue

                    # Handle None values
                    if book_title is None:
                        book_title = 'Untitled Book'
                    if author is None:
                        author = 'Unknown Author'

                    name = f"{book_title} | {author}"
                    if not name.strip():
                        name = "Untitled Book"

                    if len(name) > 100:
                        short_author = author[:20]
                        available_len = 100 - len(short_author) - 3
                        trimmed_title = book_title[:available_len] if available_len > 0 else "Untitled"
                        name = f"{trimmed_title}... | {short_author}"

                    name = name.encode("utf-8")[:100].decode("utf-8", "ignore")

                    if 1 <= len(name) <= 100:
                        choices.append({"name": name, "value": f"{book_id}"})

                await ctx.send(choices=choices)
                logger.info(choices)

            except Exception as e:  # NOQA
                await ctx.send(choices=choices)
                logger.error(f"Error in autocomplete: {e}")

    @change_chapter.autocomplete("option")
    async def chapter_option_autocomplete(self, ctx: AutocompleteContext):
        choices = [
            {"name": "next", "value": "next"}, {"name": "previous", "value": "previous"}
        ]
        await ctx.send(choices=choices)

    # Component Callbacks ---------------------------
    @component_callback('pause_audio_button')
    async def callback_pause_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Pausing Playback!')
            self.play_state = 'paused'
            ctx.voice_state.channel.voice_state.pause()
            self.session_update.stop()
            logger.warning("Auto session kill task running... Checking for inactive session in 5 minutes!")
            self.auto_kill_session.start()

            await self.update_playback_message(ctx, edit_origin=True)

    @component_callback('play_audio_button')
    async def callback_play_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Resuming Playback!')
            self.play_state = 'playing'
            ctx.voice_state.channel.voice_state.resume()
            self.session_update.start()

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            await self.update_playback_message(ctx, edit_origin=True)

    @component_callback('next_chapter_button')
    async def callback_next_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Moving to next chapter!')
            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=get_playback_rows("playing"))
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=get_playback_rows("paused"))
            ctx.voice_state.channel.voice_state.player.stop()

            # Find next chapter
            await self.move_chapter(option='next')

            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.newChapterTitle)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            if self.found_next_chapter:
                await ctx.edit(embed=embed_message)
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA
            else:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting", ephemeral=True)

            # Resetting Variable
            self.found_next_chapter = False

    @component_callback('previous_chapter_button')
    async def callback_previous_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Moving to previous chapter!')
            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=get_playback_rows("playing"))
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=get_playback_rows("paused"))
                ctx.voice_state.channel.voice_state.player.stop()
            else:
                await ctx.send(content='Error with previous chapter command, bot not active or voice not connected!', ephemeral=True)
                return

            # Find previous chapter
            await self.move_chapter(option='previous')

            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.newChapterTitle)

            if self.found_next_chapter:
                await ctx.edit(embed=embed_message)

                # Stop auto kill session task
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()

                # Resetting Variable
                self.found_next_chapter = False
                ctx.voice_state.channel.voice_state.player.stop()
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

            else:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting", ephemeral=True)

    @component_callback('stop_audio_button')
    async def callback_stop_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Stopping Playback!')
            await ctx.voice_state.channel.voice_state.stop()
            await ctx.edit_origin()
            await ctx.delete()
            # Class VARS
            self.audioObj.cleanup()  # NOQA
            self.session_update.stop()
            self.current_playback_time = 0
            self.activeSessions -= 1
            self.sessionOwner = None
            self.play_state = 'stopped'
            await ctx.voice_state.channel.disconnect()
            await self.client.change_presence(activity=None)
            # Cleanup Session
            await c.bookshelf_close_session(self.sessionID)
            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

    @component_callback('volume_up_button')
    async def callback_volume_up_button(self, ctx: ComponentContext):
        if ctx.voice_state and ctx.author.voice:
            adjustment = 0.1
            # Update Audio OBJ
            audio = self.audioObj
            self.volume = audio.volume
            audio.volume = self.volume + adjustment  # NOQA
            self.volume = audio.volume

            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            await ctx.edit_origin(embed=embed_message)
            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

    @component_callback('volume_down_button')
    async def callback_volume_down_button(self, ctx: ComponentContext):
        if ctx.voice_state and ctx.author.voice:
            adjustment = 0.1

            audio = self.audioObj
            self.volume = audio.volume
            audio.volume = self.volume - adjustment  # NOQA
            self.volume = audio.volume

            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, chapter=self.currentChapterTitle)

            await ctx.edit_origin(embed=embed_message)

            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

    @component_callback('forward_button')
    async def callback_forward_button(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)

        if not self.sessionID or not ctx.voice_state:
            await ctx.send("No active playback session. Start playback first.", ephemeral=True)
            return

        self.session_update.stop()
        ctx.voice_state.channel.voice_state.player.stop()

        # Calculate new position (30 seconds forward)
        new_position = self.currentTime + 30.0
        logger.info(f"Moving forward 30 seconds to position: {new_position}")

        # Sync to new position
        updated_time, duration, finished_book = await self.sync_playback_position(new_position)

        await c.bookshelf_close_session(self.sessionID)
        self.audioObj.cleanup()  # NOQA

        # Get current chapter info
        current_chapter = self.currentChapter
        chapter_array = self.chapterArray

        if current_chapter and chapter_array:
            # Calculate how much time is left in the current chapter
            current_chapter_end = float(current_chapter.get('end', 0))
            time_remaining_in_chapter = current_chapter_end - self.currentTime
        
            # If less than 30 seconds remain in chapter, move to next chapter
            if time_remaining_in_chapter < 30:
                # Find the next chapter
                current_chapter_id = int(current_chapter.get('id', 0))
                next_chapter_id = current_chapter_id + 1
            
                for chapter in chapter_array:
                    if int(chapter.get('id', -1)) == next_chapter_id:
                        # Found next chapter, set position to its start
                        next_position = float(chapter.get('start', 0))
                        logger.info(f"Less than 30 seconds left in chapter, moving to start of next chapter: {chapter.get('title')} at {next_position}")
                        await self.sync_playback_position(next_position)
                        break
                else:
                    # No next chapter found, just move to end of current chapter
                    next_position = current_chapter_end - 0.5  # Slight buffer to stay within chapter
                    logger.info(f"Less than 30 seconds left in chapter and no next chapter found, moving to end of current chapter: {next_position}")
                    await self.sync_playback_position(next_position)
            else:
                # Normal 30 second forward within chapter
                next_position = self.currentTime + 30.0
                logger.info(f"Moving forward 30 seconds within chapter to: {next_position}")
                await self.sync_playback_position(next_position)

        else:
            # Fallback if chapter info not available
            next_position = self.currentTime + 30.0
            logger.info(f"Moving forward 30 seconds (no chapter info) to: {next_position}")
            await self.sync_playback_position(next_position)

        audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(self.bookItemID)

        self.sessionID = sessionID
        self.currentTime = currentTime

        audio = AudioVolume(audio_obj)
        audio.ffmpeg_before_args = f"-ss {next_position}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac"

        self.audioObj = audio
        self.session_update.start()

        # Stop auto kill session task
        if self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        await ctx.edit_origin()
        await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

    @component_callback('rewind_button')
    async def callback_rewind_button(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)

        if not self.currentChapter or not self.chapterArray:
            logger.warning("Cannot move chapter: Missing chapter information")
            return False

        self.session_update.stop()
        ctx.voice_state.channel.voice_state.player.stop()
        await c.bookshelf_close_session(self.sessionID)
        self.audioObj.cleanup()  # NOQA

        # Get current chapter info
        current_chapter = self.currentChapter
        chapter_array = self.chapterArray

        # Calculate new position
        next_position = 0.0

        if current_chapter and chapter_array:
            # Calculate how much time has passed in the current chapter
            current_chapter_start = float(current_chapter.get('start', 0))
            time_in_chapter = self.currentTime - current_chapter_start
        
            # If less than 30 seconds into chapter, move to previous chapter end
            if time_in_chapter < 30:
                # Find the previous chapter
                current_chapter_id = int(current_chapter.get('id', 0))
                prev_chapter_id = current_chapter_id - 1
            
                # Check if we're in Chapter 1
                if prev_chapter_id < 0:
                    # Just go to start of current chapter
                    next_position = current_chapter_start
                    logger.info(f"Less than 30 seconds into chapter 1, moving to start of chapter: {next_position}")
                else:
                    # Find previous chapter
                    for chapter in chapter_array:
                        if int(chapter.get('id', -1)) == prev_chapter_id:
                            # Move to end of previous chapter, but subtract a small buffer to ensure we're in that chapter
                            prev_chapter_end = float(chapter.get('end', 0))
                            next_position = max(float(chapter.get('start', 0)), prev_chapter_end - 5.0)
                            logger.info(f"Less than 30 seconds into chapter, moving to end of previous chapter: {chapter.get('title')} at {next_position}")
                            break
                    else:
                        # No previous chapter found (shouldn't happen), stay at current chapter start
                        next_position = current_chapter_start
                        logger.info(f"No previous chapter found, moving to start of current chapter: {next_position}")
            else:
                # Normal 30 second rewind within chapter
                next_position = max(current_chapter_start, self.currentTime - 30.0)
                logger.info(f"Moving back 30 seconds within chapter to: {next_position}")
        else:
            # Fallback if chapter info not available
            next_position = max(0, self.currentTime - 30.0)
            logger.info(f"Moving back 30 seconds (no chapter info) to: {next_position}")

        # Use sync_playback_position helper function
        await self.sync_playback_position(next_position)

        # Get new audio object
        audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(self.bookItemID)
        self.sessionID = sessionID

        audio = AudioVolume(audio_obj)
        audio.ffmpeg_before_args = f"-ss {next_position}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac"
        self.audioObj = audio

        # Start session update
        self.session_update.start()

        # Stop auto kill session task
        if self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        await ctx.edit_origin()
        await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

    @component_callback('previous_book_button')
    async def callback_previous_book_button(self, ctx: ComponentContext):
        if not self.isSeries:
            await ctx.send("This book is not part of a series.", ephemeral=True)
            return
        
        await ctx.defer(edit_origin=True)
    
        try:
            # Get book details to extract series info
            book_details = await c.bookshelf_get_item_details(self.bookItemID)
            if not book_details or 'series' not in book_details or not book_details['series']:
                await ctx.send("Could not find series information for this book.", ephemeral=True)
                return
            
            # Extract series name
            series_name = book_details['series'].split(',')[0].strip() if ',' in book_details['series'] else book_details['series']
            current_sequence = book_details['series'].split('Book')[1].strip() if 'Book' in book_details['series'] else '0'
        
            logger.info(f"Looking for previous book in series: {series_name}, current book: {current_sequence}")
        
            # Get all books in the library to find other books in this series
            libraries = await c.bookshelf_libraries()
            all_books = []
        
            for name, (library_id, _) in libraries.items():
                books = await c.bookshelf_all_library_items(library_id)
                all_books.extend(books)
        
            # Find books that match the series
            series_books = []
            for book in all_books:
                book_id = book.get('id')
                if book_id == self.bookItemID:
                    # Skip the current book - we already have its details
                    temp_details = book_details
                else:
                    temp_details = await c.bookshelf_get_item_details(book_id)
            
                if temp_details and 'series' in temp_details and temp_details['series'] and series_name in temp_details['series']:
                    # Extract sequence number
                    seq_str = temp_details['series'].split('Book')[1].strip() if 'Book' in temp_details['series'] else '0'
                    try:
                        seq = float(seq_str)
                        series_books.append({
                            'id': book_id,
                            'title': temp_details.get('title', 'Unknown Title'),
                            'sequence': seq
                        })
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse sequence number from '{seq_str}' for book {book_id}")
        
            # Sort by sequence number
            series_books.sort(key=lambda x: x['sequence'])
        
            # Find current book index
            current_index = next((i for i, book in enumerate(series_books) if book['id'] == self.bookItemID), -1)
        
            if current_index <= 0:
                await ctx.send("This is the first book in the series.", ephemeral=True)
                return
            
            # Get previous book
            previous_book = series_books[current_index - 1]
            prev_book_id = previous_book['id']
        
            # Stop current playback
            if ctx.voice_state:
                await ctx.voice_state.channel.voice_state.stop()
                await c.bookshelf_close_session(self.sessionID)
                if self.session_update.running:
                    self.session_update.stop()
                self.play_state = 'stopped'

            # Play the previous book
            await ctx.send(f"Starting previous book in series: **{previous_book['title']}**", ephemeral=True)
        
            # Use command directly - this is a simplification and might need adjustment
            await self.play_audio(ctx, book=prev_book_id)
        
        except Exception as e:
            logger.error(f"Error finding previous book: {e}")
            await ctx.send("Error finding previous book in the series.", ephemeral=True)

    @component_callback('next_book_button')
    async def callback_next_book_button(self, ctx: ComponentContext):
        if not self.isSeries:
            await ctx.send("This book is not part of a series.", ephemeral=True)
            return
        
        await ctx.defer(edit_origin=True)
    
        try:
            # Get book details to extract series info
            book_details = await c.bookshelf_get_item_details(self.bookItemID)
            if not book_details or 'series' not in book_details or not book_details['series']:
                await ctx.send("Could not find series information for this book.", ephemeral=True)
                return
            
            # Extract series name
            series_name = book_details['series'].split(',')[0].strip() if ',' in book_details['series'] else book_details['series']
            current_sequence = book_details['series'].split('Book')[1].strip() if 'Book' in book_details['series'] else '0'
        
            logger.info(f"Looking for next book in series: {series_name}, current book: {current_sequence}")
        
            # Get all books in the library to find other books in this series
            libraries = await c.bookshelf_libraries()
            all_books = []
        
            for name, (library_id, _) in libraries.items():
                books = await c.bookshelf_all_library_items(library_id)
                all_books.extend(books)
        
            # Find books that match the series
            series_books = []
            for book in all_books:
                book_id = book.get('id')
                if book_id == self.bookItemID:
                    # Skip the current book - we already have its details
                    temp_details = book_details
                else:
                    temp_details = await c.bookshelf_get_item_details(book_id)
            
                if temp_details and 'series' in book_details and book_details['series'] and series_name in book_details['series']:
                    seq_str = temp_details['series'].split('Book')[1].strip() if 'Book' in temp_details['series'] else '0'
                    try:
                        seq = float(seq_str)
                        series_books.append({
                            'id': book_id,
                            'title': book_details['title'],
                            'sequence': seq
                        })
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse sequence number from '{seq_str}' for book {book_id}")
        
            # Sort by sequence number
            series_books.sort(key=lambda x: x['sequence'])
        
            # Find current book index
            current_index = next((i for i, book in enumerate(series_books) if book['id'] == self.bookItemID), -1)
        
            if current_index >= len(series_books) - 1 or current_index == -1:
                await ctx.send("This is the last book in the series or the series couldn't be found.", ephemeral=True)
                return
            
            # Get next book
            next_book = series_books[current_index + 1]
            next_book_id = next_book['id']

            # Stop current playback
            if ctx.voice_state:
                await ctx.voice_state.channel.voice_state.stop()
                await c.bookshelf_close_session(self.sessionID)
                if self.session_update.running:
                    self.session_update.stop()
                self.play_state = 'stopped'

            # Play the next book
            await ctx.send(f"Starting next book in series: **{next_book['title']}**", ephemeral=True)
        
            # Use command directly - this is a simplification and might need adjustment
            await self.play_audio(ctx, book=next_book_id)
        
        except Exception as e:
            logger.error(f"Error finding next book: {e}")
            await ctx.send("Error finding next book in the series.", ephemeral=True)

    # ----------------------------
    # Other non discord related functions
    # ----------------------------
