import asyncio

import pytz
from interactions import *
from interactions.api.voice.audio import AudioVolume
import bookshelfAPI as c
import settings as s
from settings import TIMEZONE
import logging
from datetime import datetime
from dotenv import load_dotenv
import random


load_dotenv()

# Logger Config
logger = logging.getLogger("bot")

# Update Frequency for session sync
updateFrequency = s.UPDATES

# Default only owner can use this bot
ownership = s.OWNER_ONLY

# Timezone
timeZone = pytz.timezone(TIMEZONE)

# Button Vars
# Book-specific buttons
component_rows_book_initial: list[ActionRow] = [
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="Pause",
            custom_id='pause_audio_button'
        ),
        Button(
            style=ButtonStyle.SUCCESS,
            label="+",
            custom_id='volume_up_button'
        ),
        Button(
            style=ButtonStyle.RED,
            label="-",
            custom_id='volume_down_button')),
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="- 30s",
            custom_id='rewind_button'
        ),
        Button(
            style=ButtonStyle.SECONDARY,
            label="+ 30s",
            custom_id='forward_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY,
            label="Previous Chapter",
            custom_id='previous_chapter_button'
        ),
        Button(
            style=ButtonStyle.PRIMARY,
            label="Next Chapter",
            custom_id='next_chapter_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.RED,
            label="Stop",
            custom_id='stop_audio_button'
        )
    )
]

component_rows_book_paused: list[ActionRow] = [
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY.SUCCESS,
            label='Play',
            custom_id='play_audio_button'
        ),
        Button(
            style=ButtonStyle.SUCCESS,
            label="+",
            custom_id='volume_up_button'
        ),
        Button(
            style=ButtonStyle.RED,
            label="-",
            custom_id='volume_down_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="- 30s",
            custom_id='rewind_button'
        ),
        Button(
            style=ButtonStyle.SECONDARY,
            label="+ 30s",
            custom_id='forward_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY,
            label="Previous Chapter",
            custom_id='previous_chapter_button'
        ),
        Button(
            style=ButtonStyle.PRIMARY,
            label="Next Chapter",
            custom_id='next_chapter_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.RED,
            label='Stop',
            custom_id='stop_audio_button'
        )
    )
]

# Podcast-specific buttons
component_rows_podcast_initial: list[ActionRow] = [
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="Pause",
            custom_id='pause_audio_button'
        ),
        Button(
            style=ButtonStyle.SUCCESS,
            label="+",
            custom_id='volume_up_button'
        ),
        Button(
            style=ButtonStyle.RED,
            label="-",
            custom_id='volume_down_button')),
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="- 30s",
            custom_id='rewind_button'
        ),
        Button(
            style=ButtonStyle.SECONDARY,
            label="+ 30s",
            custom_id='forward_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY,
            label="Previous Episode",
            custom_id='previous_episode_button'
        ),
        Button(
            style=ButtonStyle.PRIMARY,
            label="Next Episode",
            custom_id='next_episode_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.RED,
            label="Stop",
            custom_id='stop_audio_button'
        )
    )
]

component_rows_podcast_paused: list[ActionRow] = [
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY.SUCCESS,
            label='Play',
            custom_id='play_audio_button'
        ),
        Button(
            style=ButtonStyle.SUCCESS,
            label="+",
            custom_id='volume_up_button'
        ),
        Button(
            style=ButtonStyle.RED,
            label="-",
            custom_id='volume_down_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.SECONDARY,
            label="- 30s",
            custom_id='rewind_button'
        ),
        Button(
            style=ButtonStyle.SECONDARY,
            label="+ 30s",
            custom_id='forward_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.PRIMARY,
            label="Previous Episode",
            custom_id='previous_episode_button'
        ),
        Button(
            style=ButtonStyle.PRIMARY,
            label="Next Episode",
            custom_id='next_episode_button'
        )
    ),
    ActionRow(
        Button(
            style=ButtonStyle.RED,
            label='Stop',
            custom_id='stop_audio_button'
        )
    )
]

# Keep the originals for backward compatibility
component_rows_initial = component_rows_book_initial
component_rows_paused = component_rows_book_paused

# Voice Status Check

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
        self.contentTitle = ''
        self.contentDuration = None
        self.currentTime = 0.0
        self.activeSessions = 0
        self.sessionOwner = None
        # Content Segment VARS
        self.currentSegment = None
        self.segmentArray = None
        self.currentSegmentTitle = ''
        self.newSegmentTitle = ''
        self.found_next_segment = False
        self.contentFinished = False
        self.nextTime = None
        # Content Type
        self.isPodcast = False
        self.contentType = 'book'
        # Audio VARS
        self.audioObj = AudioVolume
        self.context_voice_channel = None
        self.current_playback_time = 0
        self.audio_context = None
        self.bitrate = 128000
        self.volume = 0.0
        self.placeholder = None
        self.playbackSpeed = 1.0
        self.updateFreqMulti = updateFrequency * self.playbackSpeed
        self.play_state = 'stopped'
        self.audio_message = None
        # User Vars
        self.username = ''
        self.user_type = ''
        self.current_channel = None
        self.active_guild_id = None

    # Tasks ---------------------------------
    #

    @Task.create(trigger=IntervalTrigger(seconds=updateFrequency))
    async def session_update(self):
        logger.info(f"Initializing Session Sync, current refresh rate set to: {updateFrequency} seconds")

        try:
            self.current_playback_time = self.current_playback_time + updateFrequency

            formatted_time = await time_converter(self.current_playback_time)

            # Try to update the session
            try:
                updatedTime, duration, serverCurrentTime, finished_content = await c.bookshelf_session_update(
                    item_id=self.bookItemID,
                    session_id=self.sessionID,
                    current_time=updateFrequency,
                    next_time=self.nextTime)

                logger.info(f"Successfully synced session to updated time: {updatedTime} | "
                            f"Current Playback Time: {formatted_time} | session ID: {self.sessionID}")

                # Check if content is finished
                if finished_content:
                    content_type = "podcast" if self.isPodcast else "book"
                    logger.info(f"{content_type.capitalize()} playback has finished based on session update")
                    # Could add special handling for finished content if problems occur

            except TypeError as e:
                logger.warning(f"Session update error: {e} - session may be invalid or closed")
                # Continue with task to allow segment update even if session update fails

            # Try to get current segment (chapter or episode)
            try:
                current_segment, segment_array, contentFinished, isPodcast, contentType = await c.bookshelf_get_content_segments(
                    self.bookItemID, updatedTime if 'updatedTime' in locals() else None)

                # For podcasts, we only care about the episode duration, not the entire series
                if self.isPodcast:
                    segment_title = current_segment.get('title', 'Unknown Episode')
                    logger.info(f"Current Episode Sync: {segment_title}")
                    self.currentSegment = current_segment
                else:
                    # For books, we care about chapters within the overall book
                    chapter_title = current_segment.get('title', 'Unknown Chapter')
                    logger.info(f"Current Chapter Sync: {chapter_title}")
                    self.currentSegment = current_segment


            except Exception as e:
                logger.warning(f"Error getting current segment: {e}")

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
                f"Current playback of **{self.contentTitle}** will be stopped in **60 seconds** if no activity occurs.")
            await asyncio.sleep(60)

            if channel and voice_state and self.play_state == 'paused':
                await chan_msg.edit(
                    content=f'Current playback of **{self.contentTitle}** has been stopped due to inactivity.')
                await voice_state.stop()
                await voice_state.disconnect()
                await c.bookshelf_close_session(self.sessionID)
                logger.warning("audio session deleted due to timeout.")

                # Reset Vars and close out loops
                self.current_channel = None
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
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

        # elif self.play_state == 'playing':
        #     logger.info('Verifying if session should be active')
        #     if self.current_channel is not None:
        #         channel = self.bot.fetch_channel(self.current_channel)

    # Random Functions ------------------------
    # Change Segment Function
    # Shared internal implementation
    async def _move_content(self, option: str, content_type: str):
        """
        Internal shared implementation for moving between content segments.

        :param option: 'next' or 'previous'
        :param content_type: 'chapter' or 'episode'
        """
        logger.info(f"executing command /next-{content_type}")
        currentSegment = self.currentSegment
        segmentArray = self.segmentArray
        contentFinished = self.contentFinished

        if not contentFinished:
            # Handle different navigation logic based on content type
            if content_type == 'episode':
                # For podcasts, we navigate through episodes in the array
                current_index = -1
                for i, segment in enumerate(segmentArray):
                    if segment.get('id') == currentSegment.get('id'):
                        current_index = i
                        break

                if current_index == -1:
                    return  # Segment not found

                if option == 'next' and current_index < len(segmentArray) - 1:
                    next_index = current_index + 1
                elif option == 'previous' and current_index > 0:
                    next_index = current_index - 1
                else:
                    return  # No valid next/previous segment

                # Get the target segment
                target_segment = segmentArray[next_index]

                # Stop current session and start new one with the target segment
                self.session_update.stop()
                await c.bookshelf_close_session(self.sessionID)

                # Set the new segment info
                self.newSegmentTitle = target_segment.get('title')

                logger.info(f"Selected Episode: {self.newSegmentTitle}")

                # Get new audio object
                audio_obj, currentTime, sessionID, contentTitle, contentDuration = await c.bookshelf_audio_obj(
                    self.bookItemID)
                self.sessionID = sessionID
                self.currentTime = currentTime
                self.contentDuration = contentDuration

                # Create audio with the new start time
                audio = AudioVolume(audio_obj)
                start_time = target_segment.get('start', 0)
                audio.ffmpeg_before_args = f"-ss {start_time}"
                audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
                self.audioObj = audio

                # Set next time
                self.nextTime = start_time

                # Send manual sync
                await c.bookshelf_session_update(
                    item_id=self.bookItemID,
                    session_id=self.sessionID,
                    current_time=updateFrequency - 0.5,
                    next_time=self.nextTime
                )

                # Reset next time
                self.nextTime = None
                self.session_update.start()
                self.found_next_segment = True

            else:  # content_type == 'chapter'
                # Original logic for books with chapters
                currentSegmentID = int(currentSegment.get('id'))
                if option == 'next':
                    nextSegmentID = currentSegmentID + 1
                else:
                    nextSegmentID = currentSegmentID - 1

                for segment in segmentArray:
                    segmentID = int(segment.get('id'))

                    if nextSegmentID == segmentID:
                        self.session_update.stop()
                        await c.bookshelf_close_session(self.sessionID)
                        segmentStart = float(segment.get('start'))
                        self.newSegmentTitle = segment.get('title')

                        logger.info(f"Selected Chapter: {self.newSegmentTitle}, Starting at: {segmentStart}")

                        audio_obj, currentTime, sessionID, contentTitle, contentDuration = await c.bookshelf_audio_obj(
                            self.bookItemID)
                        self.sessionID = sessionID
                        self.currentTime = currentTime
                        self.contentDuration = contentDuration

                        audio = AudioVolume(audio_obj)
                        audio.ffmpeg_before_args = f"-ss {segmentStart}"
                        audio.ffmpeg_args = f"-ar 44100 -acodec aac -re"
                        self.audioObj = audio

                        # Set next time to new segment time
                        self.nextTime = segmentStart

                        # Send manual next segment sync
                        await c.bookshelf_session_update(
                            item_id=self.bookItemID,
                            session_id=self.sessionID,
                            current_time=updateFrequency - 0.5,
                            next_time=self.nextTime
                        )
                        # Reset Next Time to None before starting task again
                        self.nextTime = None
                        self.session_update.start()
                        self.found_next_segment = True

    # Public methods with clear user-facing names
    async def move_chapter(self, option: str):
        """Move to the next or previous chapter in an audiobook."""
        await self._move_content(option, 'chapter')

    async def move_episode(self, option: str):
        """Move to the next or previous episode in a podcast."""
        await self._move_content(option, 'episode')

    def modified_message(self, color, segment):
        """
        Create an embedded message for the current playback.
    
        :param color: The color to use for the embed
        :param segment_title: The title of the current chapter or episode
        :return: Embed message
        """
        now = datetime.now(tz=timeZone)
        formatted_time = now.strftime("%m-%d %H:%M:%S")

        # Get the segment title from the parameter
        segment_title = segment.get('title') if isinstance(segment, dict) else segment

        # Set appropriate labels based on content type
        if self.isPodcast:
            segment_type = "Episode"
            content_type_display = "Podcast"

            # For podcasts, try to get additional metadata
            episode_number = ""
            season_number = ""

            if self.currentSegment:
                if 'episode_number' in self.currentSegment:
                    episode_number = f" #{self.currentSegment['episode_number']}"
            
                if 'season_number' in self.currentSegment:
                    season_number = f" (Season {self.currentSegment['season_number']})"
                
            # Combine for display
            segment_display = f"{segment_title}{episode_number}{season_number}"
        
            # Check if we have a publish date
            publish_date = ""
            if self.currentSegment and 'publishedAt' in self.currentSegment:
                try:
                    # Convert unix timestamp to readable date
                    publish_timestamp = self.currentSegment['publishedAt'] / 1000
                    publish_date_obj = datetime.fromtimestamp(publish_timestamp)
                    publish_date = f"\nPublished: **{publish_date_obj.strftime('%Y-%m-%d')}**"
                except (ValueError, TypeError):
                    # Handle date conversion errors
                    pass


        else:
            segment_type = "Chapter"
            content_type_display = "Audiobook"
            segment_display = segment_title
            publish_date = ""

        # Create embedded message
        embed_message = Embed(
            title=f"{self.contentTitle}",
            description=f"Currently playing {content_type_display}: {self.contentTitle}",
            color=color,
        )

        # Convert book duration into appropriate times
        duration = self.contentDuration
        TimeState = 'Seconds'
        _time = duration
        if self.contentDuration >= 60 and self.contentDuration < 3600:
            _time = round(duration / 60, 2)
            TimeState = 'Minutes'
        elif self.contentDuration >= 3600:
            _time = round(duration / 3600, 2)
            TimeState = 'Hours'

        formatted_duration = f"{_time} {TimeState}"

        # Add ABS user info
        user_info = f"Username: **{self.username}**\nUser Type: **{self.user_type}**"
        embed_message.add_field(name='ABS Information', value=user_info)

        # Create playback info field with content-appropriate terminology
        playback_info = (
            f"Current State: **{self.play_state.upper()}**\n"
            f"Content Type: **{content_type_display}**\n"
            f"Current {segment_type}: **{segment_display}**{publish_date}\n"
            f"Duration: **{formatted_duration}**\n"
            f"Current volume: **{round(self.volume * 100)}%**"
        )

        embed_message.add_field(name='Playback Information', value=playback_info)

        # Add media image (If using HTTPS)
        embed_message.add_image(self.cover_image)

        # Add helpful commands for the content type
        if self.isPodcast:
            help_text = "Commands: `/change-episode` `/start-podcast` `/reset-podcast`"
        else:
            help_text = "Commands: `/change-chapter`"

        embed_message.footer = f'Powered by Bookshelf Traveller 🕮 | {s.versionNumber} | Last Update: {formatted_time}'

        return embed_message

    # Commands --------------------------------

    # Main play command, place class variables here since this is required to play audio
    @slash_command(name="play", description="Play audio from ABS server", dm_permission=False)
    @slash_option(name="content", description="Enter title or 'random' for a surprise", required=True,
                  opt_type=OptionType.STRING,
                  autocomplete=True)
    @slash_option(name="startover",
                  description="Start audiobook or podcast episode from the beginning instead of resuming",
                  opt_type=OptionType.BOOLEAN)
    @slash_option(name="startseries",
                  description="Start podcast from first episode without resetting watch status",
                  opt_type=OptionType.BOOLEAN)
    @slash_option(name="resetseries",
                  description="Reset all episodes in podcast series to unwatched and start from beginning",
                  opt_type=OptionType.BOOLEAN)
    async def play_audio(self, ctx: SlashContext, content: str, startover=False, startseries=False, resetseries=False):
        # Check for ownership if enabled
        if ownership:
            if ctx.author.id not in ctx.bot.owners:
                logger.warning(f'User {ctx.author} attempted to use /play, and OWNER_ONLY is enabled!')
                await ctx.send(
                    content="Ownership enabled and you are not authorized to use this command. Contact bot owner.")
                return

        # Check bot is ready, if not exit command
        if not self.bot.is_ready or not ctx.author.voice:
            await ctx.send(content="Bot is not ready or author not in voice channel, please try again later.",
                           ephemeral=True)
            return

        logger.info(f"executing command /play")

        # Verify options are valid and not conflicting
        option_count = sum([1 for opt in [startover, startseries, resetseries] if opt])
        if option_count > 1:
            await ctx.send(content="Please select only one option: startover, startseries, or resetseries.", ephemeral=True)
            return

        # Defer the response right away to prevent "interaction already responded to" errors
        await ctx.defer(ephemeral=True)

        # Handle 'random' book selection here
        random_selected = False
        random_book_title = None
        contentTitle = "Unknown Content"

        content_lower = content.lower()

        # Check for special keywords
        if content_lower in ['random', 'randompodcast', 'randomepisode']:
            try:
                all_titles = await c.bookshelf_get_valid_books()
            
                if not all_titles:
                    await ctx.send(content="No content found in your library.", ephemeral=True)
                    return
            
                # Filter content based on keyword
                if content_lower == 'random':
                    # Random audiobook (exclude podcasts)
                    logger.info('Random audiobook selection requested!')
                    filtered_titles = [item for item in all_titles if item.get('mediaType') != 'podcast']
                    if not filtered_titles:
                        await ctx.send(content="No audiobooks found in your library for random selection.", ephemeral=True)
                        return
                    logger.info(f"Found {len(filtered_titles)} audiobooks for random selection")
                
                elif content_lower == 'randompodcast':
                    # Random podcast, will start from first episode
                    logger.info('Random podcast selection requested!')
                    filtered_titles = [item for item in all_titles if item.get('mediaType') == 'podcast']
                    if not filtered_titles:
                        await ctx.send(content="No podcasts found in your library for random selection.", ephemeral=True)
                        return
                    logger.info(f"Found {len(filtered_titles)} podcasts for random selection")
                    # Force startseries flag for randompodcast
                    startseries = True
                
                elif content_lower == 'randomepisode':
                    # Random episode from any podcast
                    logger.info('Random podcast episode selection requested!')
                    filtered_titles = [item for item in all_titles if item.get('mediaType') == 'podcast']
                    if not filtered_titles:
                        await ctx.send(content="No podcasts found in your library for random episode selection.", ephemeral=True)
                        return
                    logger.info(f"Found {len(filtered_titles)} podcasts to select random episode from")

                # Select random content from filtered list
                titles_count = len(filtered_titles)
                random_title_index = random.randint(0, titles_count - 1)
                random_content = filtered_titles[random_title_index]
                random_content_title = random_content.get('title')
                content = random_content.get('id')
                random_selected = True

                logger.info(f'Randomly selected: {random_content_title}')
            
                # For randomepisode, we'll select a random episode later after getting the episode list
                if content_lower == 'randomepisode':
                    logger.info(f'Will select random episode from podcast: {random_content_title}')

            except Exception as e:
                logger.error(f"Error selecting random content: {e}")
                await ctx.send(content=f"Error selecting random content: {str(e)}", ephemeral=True)
                return

        try:
            # Get content information
            current_segment, segment_array, contentFinished, isPodcast, contentType = await c.bookshelf_get_content_segments(item_id=content)

            if current_segment is None:
                await ctx.send(content="Error retrieving content information. The item may be invalid or inaccessible.", ephemeral=True)
                return

            # Handle randomepisode selection - now that we have the episodes list
            if content_lower == 'randomepisode' and segment_array and isPodcast:
                # Select random episode from this podcast
                episode_count = len(segment_array)
                if episode_count > 0:
                    random_episode_index = random.randint(0, episode_count - 1)
                    random_episode = segment_array[random_episode_index]
                    current_segment = random_episode
                    logger.info(f"Randomly selected episode: {current_segment.get('title')} from {random_content_title}")
                else:
                    logger.warning(f"No episodes found in podcast: {random_content_title}")
                    await ctx.send(content=f"No episodes found in selected podcast: {random_content_title}", ephemeral=True)
                    return

            # Validate podcast-specific options
            if not isPodcast and (startseries or resetseries):
                await ctx.send(content="The 'startseries' and 'resetseries' options are for podcasts only.", ephemeral=True)
                return


            if self.activeSessions >= 1:
                await ctx.send(content=f"Bot can only play one session at a time, please stop your other active session and try again! Current session owner: {self.sessionOwner}", ephemeral=True)
                return

            # Handle content finished status
            if contentFinished and not (startover or startseries or resetseries):
                if isPodcast:
                    await ctx.send(content=f"This podcast series is marked as finished. Use 'startover' to restart the current episode, 'startseries' to start from the first episode, or 'resetseries' to reset all episodes.", ephemeral=True)
                else:
                    await ctx.send(content=f"This audiobook is marked as finished. Use 'startover: True' to play it from the beginning.", ephemeral=True)
                return

            # Get Playback URI, Starts new session
            result = await c.bookshelf_audio_obj(content)
        
            # Check if None was returned
            if result is None or result[0] is None:
                await ctx.send(content="Error: Could not get audio playback URL for this item. This might be a podcast episode issue.", ephemeral=True)
                return
            
            # Unpack the results
            audio_obj, currentTime, sessionID, contentTitle, contentDuration = result

            # Handle podcast series options
            if isPodcast and (startseries or resetseries):
                # Handle podcast series options
                if resetseries:
                    # Reset all episodes to unwatched
                    result = await c.bookshelf_reset_podcast_progress(content)
                    if not result:
                        await ctx.send(content="Failed to reset podcast episodes. Please try again later.", ephemeral=True)
                        return
                    logger.info(f"Reset all episodes in podcast: {random_content_title or contentTitle}")
            
                # Find the first episode
                if segment_array and len(segment_array) > 0:
                    # Sort episodes by publication date or episode number
                    segment_array.sort(key=lambda x: x.get('publishedAt', 0) or 0)
                
                    # Get the first episode
                    first_segment = segment_array[0]
                    self.currentSegment = first_segment
                    self.currentSegmentTitle = first_segment.get('title', 'Episode 1')
                    logger.info(f"Setting to first episode: {self.currentSegmentTitle}")
                
                    # Set to beginning of episode
                    currentTime = 0

            # Handle randomepisode - use selected episode
            elif content_lower == 'randomepisode' and isPodcast:
                self.currentSegment = current_segment
                self.currentSegmentTitle = current_segment.get('title', 'Unknown Episode')
                # Start from beginning of the episode
                currentTime = 0
                logger.info(f"Setting to random episode: {self.currentSegmentTitle}")

            # Handle startover option (works for both content types)
            elif startover:
                logger.info(f"Starting {contentType} from beginning with startover option")
                currentTime = 0
            
                if not isPodcast:
                    # For books, find the first chapter
                    if segment_array and len(segment_array) > 0:
                        # Sort by start time
                        segment_array.sort(key=lambda x: float(x.get('start', 0)))
                    
                        # Get the first chapter
                        first_segment = segment_array[0]
                        self.currentSegment = first_segment
                        self.currentSegmentTitle = first_segment.get('title', 'Chapter 1')
                        logger.info(f"Setting to first chapter: {self.currentSegmentTitle}")
                else:
                    # For podcasts, we're simply restarting the current episode
                    self.currentSegment = current_segment
                    self.currentSegmentTitle = current_segment.get('title', 'Unknown Episode')
                    logger.info(f"Restarting episode from beginning: {self.currentSegmentTitle}")

            # Get Book Cover URL
            cover_image = await c.bookshelf_cover_image(content)

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
            self.bookItemID = content
            self.contentTitle = contentTitle
            self.audioObj = audio
            self.currentTime = currentTime
            self.current_playback_time = 0
            self.audio_context = ctx
            self.active_guild_id = ctx.guild_id
            self.contentDuration = contentDuration

            # Content type vars
            self.isPodcast = isPodcast
            self.contentType = contentType

            # Content Segment Vars
            if not (startover or startseries or resetseries):
                # Normal resume behavior
                self.currentSegment = current_segment
                self.currentSegmentTitle = current_segment.get('title', 'Unknown Segment')
            # else already set above for startover/startseries
        
            self.segmentArray = segment_array
            self.contentFinished = contentFinished
            self.current_channel = ctx.channel_id
            self.play_state = 'playing'
        
            # For podcasts, set duration to episode duration rather than entire podcast duration
            if isPodcast and self.currentSegment:
                # Get the episode-specific duration for podcasts
                episode_duration = self.currentSegment.get('duration', 0)
                if episode_duration > 0:
                    # Override the contentDuration for podcasts to show episode duration
                    self.contentDuration = episode_duration
                    logger.info(f"Using individual episode duration for podcast: {episode_duration} seconds")


            # Create embedded message
            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.currentSegmentTitle)

            # check if bot currently connected to voice
            if not ctx.voice_state:
                # if we haven't already joined a voice channel
                try:
                    # Connect to voice channel
                    await ctx.author.voice.channel.connect()

                    # Start Tasks
                    self.session_update.start()

                    # Build the start message
                    if random_selected:
                        if content_lower == 'random':
                            start_message = f"🎲 Randomly selected audiobook: **{random_content_title}**\n"
                        elif content_lower == 'randompodcast':
                            start_message = f"🎲 Randomly selected podcast: **{random_content_title}**\n"
                        elif content_lower == 'randomepisode':
                            start_message = f"🎲 Randomly selected episode from podcast **{random_content_title}**\n"
                    else:
                        start_message = ""

                    # Add appropriate content type message
                    if isPodcast:
                        if startseries or content_lower == 'randompodcast':
                            start_message += f"Starting podcast from first episode: **{self.currentSegmentTitle}**"
                        elif content_lower == 'randomepisode':
                            start_message += f"Playing random episode: **{self.currentSegmentTitle}**"
                        elif startover:
                            start_message += f"Restarting podcast episode: **{self.currentSegmentTitle}**"
                        else:
                            start_message += f"Playing podcast episode: **{self.currentSegmentTitle}**"
                    else:
                        if startover:
                            start_message += f"Starting audiobook from the beginning"
                        else:
                            start_message += f"Resuming audiobook playback"


                    # Stop auto kill session task
                    if self.auto_kill_session.running:
                        self.auto_kill_session.stop()

                    # Choose the appropriate button set based on content type
                    if self.isPodcast:
                        content_rows = component_rows_podcast_initial
                        content_type_str = "podcast"
                    else:
                        content_rows = component_rows_book_initial
                        content_type_str = "audiobook"

                    self.audio_message = await ctx.send(content=start_message, embed=embed_message,
                                                        components=content_rows)

                    # Log appropriate message
                    if isPodcast:
                        if startseries or content_lower == 'randompodcast':
                            logger.info(f"Beginning podcast playback from first episode")
                        elif content_lower == 'randomepisode':
                            logger.info(f"Playing random podcast episode")
                        elif startover:
                            logger.info(f"Restarting podcast episode from beginning")
                        else:
                            logger.info(f"Resuming podcast episode playback")
                    else:
                        logger.info(f"Beginning audiobook playback" + (" from the beginning" if startover else ""))

                    self.activeSessions += 1

                    activity_name = f"{self.contentTitle} ({contentType.capitalize()})"
                    await self.client.change_presence(activity=Activity.create(name=activity_name,
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
            import traceback
            full_trace = traceback.format_exc()
            logger.error(f"Full stack trace:\n{full_trace}")
            await ctx.send(content=f"An error occurred: {str(e)}", ephemeral=True)

    # Pause audio, stops tasks, keeps session active.
    @slash_command(name="pause", description="pause audio", dm_permission=False)
    async def pause_audio(self, ctx):
        if ctx.voice_state:
            await ctx.send("Pausing Audio", ephemeral=True)
            logger.info(f"executing command /pause")
            ctx.voice_state.pause()
            logger.info("Pausing Audio")
            self.play_state = 'paused'
            # Stop Any Tasks Running
            if self.session_update.running:
                self.session_update.stop()
                # self.terminal_clearer.stop()
            # Start auto kill session check
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
                # Stop auto kill session task
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()
                # Start session
                self.play_state = 'playing'
                self.session_update.start()
                # self.terminal_clearer.start()
            else:
                await ctx.send(content="Bot or author isn't connected to channel, aborting.",
                               ephemeral=True)

    @check(ownership_check)
    @slash_command(name="change-chapter", description="play next or previous chapter in an audiobook.", dm_permission=False)
    @slash_option(name="option", description="Select 'next' or 'previous'", opt_type=OptionType.STRING,
                  autocomplete=True, required=True)
    async def change_chapter(self, ctx, option: str):
        if ctx.voice_state:
            if self.isPodcast:
                await ctx.send(content="This command is for audiobooks only. For podcasts, use /change-episode.", ephemeral=True)
                return

            await self.move_chapter(option)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            await ctx.send(content=f"Moving to chapter: {self.newSegmentTitle}", ephemeral=True)

            await ctx.voice_state.play(self.audioObj)

            if not self.found_next_segment:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting",
                               ephemeral=True)
            # Resetting Variable
            self.found_next_segment = False
        else:
            await ctx.send(content="Bot or author isn't connected to channel, aborting.", ephemeral=True)

    @check(ownership_check)
    @slash_command(name="change-episode", description="Play next or previous episode in a podcast.", dm_permission=False)
    @slash_option(name="option", description="Select 'next' or 'previous'", opt_type=OptionType.STRING,
                  autocomplete=True, required=True)
    async def change_episode(self, ctx, option: str):
        if ctx.voice_state:
            if not self.isPodcast:
                await ctx.send(content="This command is for podcasts only. For audiobooks, use /change-chapter.", ephemeral=True)
                return
        
            await self.move_episode(option)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            await ctx.send(content=f"Moving to episode: {self.newSegmentTitle}", ephemeral=True)

            await ctx.voice_state.play(self.audioObj)

            if not self.found_next_segment:
                await ctx.send(content=f"Podcast finished or no new episode found, aborting",
                               ephemeral=True)
            # Resetting Variable
            self.found_next_segment = False
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
                current_segment, segment_array, contentFinished, isPodcast, contentType = await c.bookshelf_get_content_segments(
                    self.bookItemID)
                self.currentSegmentTitle = current_segment.get('title')
            except Exception as e:
                logger.error(f"Error trying to fetch segment title. {e}")

            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.currentSegmentTitle)

            # Select the appropriate button set based on content type and play state
            if self.isPodcast:
                if self.play_state == "playing":
                    components = component_rows_podcast_initial
                else:
                    components = component_rows_podcast_paused
            else:
                if self.play_state == "playing":
                    components = component_rows_book_initial
                else:
                    components = component_rows_book_paused

            await ctx.send(embed=embed_message, components=components, ephemeral=True)
        else:
            return await ctx.send("Bot not in voice channel or an error has occurred. Please try again later!",
                                  ephemeral=True)

    # -----------------------------
    # Auto complete options below
    # -----------------------------
    @play_audio.autocomplete("content")
    async def search_media_auto_complete(self, ctx: AutocompleteContext):
        user_input = ctx.input_text
        choices = []
        logger.info(f"Autocomplete input: '{user_input}'")

        if user_input == "":
            try:
                # Only show the main random option initially to avoid crowding
                choices.append({"name": "📚 Random Book (Surprise me!)", "value": "random"})

                # Get recent sessions
                formatted_sessions_string, data = await c.bookshelf_listening_stats()
                valid_session_count = 0
                skipped_session_count = 0

                for session in data.get('recentSessions', []):
                    try:
                        # Get essential IDs
                        bookID = session.get('bookId') or session.get('podcastEpisodeId')
                        itemID = session.get('libraryItemId')
                        media_type = session.get('mediaType', 'book')

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
                            title = 'Untitled Content'

                        # Apply default value for None author
                        if display_author is None:
                            logger.info(f"Found session with None author for itemID: {itemID}, title: {title}")
                            display_author = 'Unknown Creator'

                        # Add content type indicator
                        content_type_icon = "🎙️" if media_type == "podcast" else "📚"

                        # Format name with smart truncation
                        name = f"{content_type_icon} {title} | {display_author}"
                        if len(name) > 100:
                            # First try title only
                            if len(title) <= 98: # Allow room for icon
                                name = title
                                logger.info(f"Truncated name to title only: {title}")
                            else:
                                # Try smart truncation with author
                                short_author = display_author[:20]
                                available_len = 98 - len(short_author) - 5  # Allow for "... | " and icon
                                trimmed_title = title[:available_len] if available_len > 0 else "Untitled"
                                name = f"{content_type_icon} {trimmed_title}... | {short_author}"
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

        # When user types "random", show all random options to hint at the full capability
        elif user_input == "random" or user_input.startswith("random"):
            choices = [
                {"name": "🎲 random - Select random audiobook", "value": "random"},
                {"name": "🎙️ randompodcast - Select random podcast (from first episode)", "value": "randompodcast"},
                {"name": "🎙️ randomepisode - Select random episode from any podcast", "value": "randomepisode"}
            ]
            await ctx.send(choices=choices)

        # For "randompodcast" or "randomepisode", just show that specific option 
        elif user_input == "randompodcast" or user_input.startswith("randompodcast"):
            choices = [{"name": "🎙️ randompodcast - Select random podcast (from first episode)", "value": "randompodcast"}]
            await ctx.send(choices=choices)
        
        elif user_input == "randomepisode" or user_input.startswith("randomepisode"):
            choices = [{"name": "🎙️ randomepisode - Select random episode from any podcast", "value": "randomepisode"}]
            await ctx.send(choices=choices)

        else:
            # Handle user input search for normal content
            ctx.deferred = True
            try:
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

                            # Search for books
                            book_dataset = data.get('book', [])
                            for book in book_dataset:
                                authors_list = []
                                title = book['libraryItem']['media']['metadata']['title']
                                authors_raw = book['libraryItem']['media']['metadata']['authors']

                                for author in authors_raw:
                                    name = author.get('name')
                                    authors_list.append(name)

                                author = ', '.join(authors_list)
                                book_id = book['libraryItem']['id']

                                # Add to list if not already present (avoid duplicates)
                                new_item = {'id': book_id, 'title': title, 'author': author, 'type': 'book'}
                                if not any(item['id'] == book_id for item in found_titles):
                                    found_titles.append(new_item)

                            # Search for podcasts
                            podcast_dataset = data.get('podcast', [])
                            for podcast in podcast_dataset:
                                title = podcast['libraryItem']['media']['metadata']['title']
                                author = podcast['libraryItem']['media']['metadata'].get('author', 'Unknown Author')
                                podcast_id = podcast['libraryItem']['id']

                                # Add to list if not already present (avoid duplicates)
                                new_item = {'id': podcast_id, 'title': title, 'author': author, 'type': 'podcast'}
                                if not any(item['id'] == podcast_id for item in found_titles):
                                    found_titles.append(new_item)

                    except Exception as e:
                        logger.error(f"Error searching library {library_iD}: {e}")
                        continue  # Continue to next library even if this one fails

                # Process all found titles into choices for autocomplete
                for content in found_titles:
                    content_title = content.get('title', 'Unknown').strip()
                    author = content.get('author', 'Unknown').strip()
                    content_id = content.get('id')
                    content_type = content.get('type', 'book')

                    if not content_id:
                        continue

                    # Handle None values
                    if content_title is None:
                        content_title = 'Untitled Content'
                    if author is None:
                        author = 'Unknown Creator'

                    # Add content type icon
                    content_type_icon = "🎙️" if content_type == "podcast" else "📚"

                    name = f"{content_type_icon} {content_title} | {author}"
                    if not name.strip():
                        name = "Untitled Content"

                    if len(name) > 100:
                        short_author = author[:20]
                        available_len = 98 - len(short_author) - 3
                        trimmed_title = content_title[:available_len] if available_len > 0 else "Untitled"
                        name = f"{content_type_icon} {trimmed_title}... | {short_author}"

                    name = name.encode("utf-8")[:100].decode("utf-8", "ignore")

                    if 1 <= len(name) <= 100:
                        choices.append({"name": name, "value": f"{content_id}"})

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
            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.currentSegmentTitle)
            await ctx.edit_origin(content="Play", components=component_rows_paused, embed=embed_message)

    @component_callback('play_audio_button')
    async def callback_play_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            logger.info('Resuming Playback!')
            self.play_state = 'playing'
            ctx.voice_state.channel.voice_state.resume()
            self.session_update.start()
            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.currentSegmentTitle)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            await ctx.edit_origin(components=component_rows_initial, embed=embed_message)

    @component_callback('next_chapter_button')
    async def callback_next_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            if self.isPodcast:
                await ctx.send(content="This button is for audiobooks only. Please use the 'Next Episode' button.", ephemeral=True)
                return

            logger.info('Moving to next chapter!')
            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=component_rows_book_initial)
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=component_rows_book_paused)
                ctx.voice_state.channel.voice_state.player.stop()

            # Find next chapter
            await self.move_chapter(option='next')

            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.newSegmentTitle)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            if self.found_next_segment:
                await ctx.edit(embed=embed_message)
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA
            else:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting", ephemeral=True)

            # Resetting Variable
            self.found_next_segment = False

    @component_callback('previous_chapter_button')
    async def callback_previous_chapter_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            if self.isPodcast:
                await ctx.send(content="This button is for audiobooks only. Please use the 'Previous Episode' button.", ephemeral=True)
                return

            logger.info('Moving to previous chapter!')
            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=component_rows_book_initial)
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=component_rows_book_paused)
                ctx.voice_state.channel.voice_state.player.stop()
            else:
                await ctx.send(content='Error with previous chapter command, bot not active or voice not connected!',
                               ephemeral=True)
                return

            # Find previous chapter
            await self.move_chapter(option='previous')

            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.newSegmentTitle)

            if self.found_next_segment:
                await ctx.edit(embed=embed_message)

                # Stop auto kill session task
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()

                # Resetting Variable
                self.found_next_segment = False
                ctx.voice_state.channel.voice_state.player.stop()
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

            else:
                await ctx.send(content=f"Book Finished or No New Chapter Found, aborting", ephemeral=True)

    @component_callback('next_episode_button')
    async def callback_next_episode_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            if not self.isPodcast:
                await ctx.send(content="This button is for podcasts only. Please use the 'Next Chapter' button.", ephemeral=True)
                return
            
            logger.info('Moving to next episode!')
            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=component_rows_podcast_initial)
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=component_rows_podcast_paused)
                ctx.voice_state.channel.voice_state.player.stop()

            # Find next episode
            await self.move_episode(option='next')

            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.newSegmentTitle)

            # Stop auto kill session task
            if self.auto_kill_session.running:
                logger.info("Stopping auto kill session backend task.")
                self.auto_kill_session.stop()

            if self.found_next_segment:
                await ctx.edit(embed=embed_message)
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA
            else:
                await ctx.send(content=f"Podcast finished or no new episode found, aborting", ephemeral=True)

            # Resetting Variable
            self.found_next_segment = False

    @component_callback('previous_episode_button')
    async def callback_previous_episode_button(self, ctx: ComponentContext):
        if ctx.voice_state:
            if not self.isPodcast:
                await ctx.send(content="This button is for podcasts only. Please use the 'Previous Chapter' button.", ephemeral=True)
                return
            
            logger.info('Moving to previous episode!')
            await ctx.defer(edit_origin=True)

            if self.play_state == 'playing':
                await ctx.edit_origin(components=component_rows_podcast_initial)
                ctx.voice_state.channel.voice_state.player.stop()
            elif self.play_state == 'paused':
                await ctx.edit_origin(components=component_rows_podcast_paused)
                ctx.voice_state.channel.voice_state.player.stop()
            else:
                await ctx.send(content='Error with previous episode command, bot not active or voice not connected!',
                               ephemeral=True)
                return

            # Find previous episode
            await self.move_episode(option='previous')

            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.newSegmentTitle)

            if self.found_next_segment:
                await ctx.edit(embed=embed_message)

                # Stop auto kill session task
                if self.auto_kill_session.running:
                    logger.info("Stopping auto kill session backend task.")
                    self.auto_kill_session.stop()

                # Resetting Variable
                self.found_next_segment = False
                ctx.voice_state.channel.voice_state.player.stop()
                await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

            else:
                await ctx.send(content=f"Podcast finished or no new episode found, aborting", ephemeral=True)

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
            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.currentSegmentTitle)

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
            embed_message = self.modified_message(color=ctx.author.accent_color, segment=self.currentSegmentTitle)

            await ctx.edit_origin(embed=embed_message)

            logger.info(f"Set Volume {round(self.volume * 100)}")  # NOQA

    @component_callback('forward_button')
    async def callback_forward_button(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)
        self.session_update.stop()
        ctx.voice_state.channel.voice_state.player.stop()
        await c.bookshelf_close_session(self.sessionID)
        self.audioObj.cleanup()  # NOQA

        audio_obj, currentTime, sessionID, bookTitle, bookDuration = await c.bookshelf_audio_obj(self.bookItemID)

        self.sessionID = sessionID
        self.currentTime = currentTime

        print(self.currentTime)

        self.nextTime = self.currentTime + 30.0
        logger.info(f"Moving to time using forward:  {self.nextTime}")

        audio = AudioVolume(audio_obj)

        audio.ffmpeg_before_args = f"-ss {self.nextTime}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac"

        # Send manual next chapter sync
        await c.bookshelf_session_update(item_id=self.bookItemID, session_id=self.sessionID,
                                         current_time=updateFrequency - 0.5, next_time=self.nextTime)

        self.audioObj = audio
        self.session_update.start()
        self.nextTime = None

        # Stop auto kill session task
        if self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        await ctx.edit_origin()
        await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

    @component_callback('rewind_button')
    async def callback_rewind_button(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)
        self.session_update.stop()
        ctx.voice_state.channel.voice_state.player.stop()
        await c.bookshelf_close_session(self.sessionID)
        self.audioObj.cleanup()  # NOQA
        audio_obj, currentTime, sessionID, contentTitle, contentDuration = await c.bookshelf_audio_obj(self.bookItemID)

        self.currentTime = currentTime
        self.sessionID = sessionID
        self.nextTime = self.currentTime - 30.0
        logger.info(f"Moving to time using rewind: {self.nextTime}")

        audio = AudioVolume(audio_obj)

        audio.ffmpeg_before_args = f"-ss {self.nextTime}"
        audio.ffmpeg_args = f"-ar 44100 -acodec aac"

        # Send manual next chapter sync
        await c.bookshelf_session_update(item_id=self.bookItemID, session_id=self.sessionID,
                                         current_time=updateFrequency - 0.5, next_time=self.nextTime)

        self.audioObj = audio
        self.session_update.start()
        self.nextTime = None

        # Stop auto kill session task
        if self.auto_kill_session.running:
            logger.info("Stopping auto kill session backend task.")
            self.auto_kill_session.stop()

        await ctx.edit_origin()
        await ctx.voice_state.channel.voice_state.play(self.audioObj)  # NOQA

    # ----------------------------
    # Other non discord related functions
    # ----------------------------
