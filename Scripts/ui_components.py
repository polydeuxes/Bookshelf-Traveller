from interactions import ActionRow, Button, ButtonStyle, Embed

# --- Playback Rows ---

def get_playback_rows(play_state="playing", has_chapters=True, is_podcast=False, is_series=False, is_first_in_series=False, is_last_in_series=False, repeat_enabled=False):
    """
    Return the appropriate button rows for playback - unified function for all media types.
    
    Args:
        play_state: "playing" or "paused"
        has_chapters: Whether the media has chapter data
        is_podcast: Whether the media is a podcast
        is_series: Whether the media is part of a series
        is_first_in_series: Whether this is the first book in a series
        is_last_in_series: Whether this is the last book in a series
        repeat_enabled: Whether repeat mode is enabled
    
    Returns:
        List of ActionRow objects with appropriate buttons
    """
    is_paused = play_state == "paused"

    # Row 1: Volume and time controls
    row1 = ActionRow(
        Button(style=ButtonStyle.DANGER, label="-", custom_id='volume_down_button'),
        Button(style=ButtonStyle.SUCCESS, label="+", custom_id='volume_up_button'),
        Button(style=ButtonStyle.SECONDARY, label="-30s", custom_id='rewind_button'),
        Button(style=ButtonStyle.SECONDARY, label="+30s", custom_id='forward_button')
    )

    # Row 2: Playback controls
    row2 = ActionRow(
        Button(
            style=ButtonStyle.SECONDARY if not is_paused else ButtonStyle.SUCCESS,
            label="Resume" if is_paused else "Pause",
            custom_id='play_audio_button' if is_paused else 'pause_audio_button'
        ),
        Button(
            style=ButtonStyle.SUCCESS if repeat_enabled else ButtonStyle.SECONDARY,
            label="Repeat" if repeat_enabled else "Repeat",
            custom_id='toggle_repeat_button'
        ),
        Button(
            style=ButtonStyle.DANGER, 
            label="Stop", 
            custom_id='stop_audio_button'
            )
    )
    
    # Start with basic rows
    rows = [row1, row2]

    # Add chapter or episode navigation if available
    if has_chapters and not is_podcast:
        # Add chapter navigation as row 3
        rows.append(ActionRow(
            Button(style=ButtonStyle.PRIMARY, label="Prior Chapter", custom_id='previous_chapter_button'),
            Button(style=ButtonStyle.PRIMARY, label="Next Chapter", custom_id='next_chapter_button')
        ))
    elif is_podcast:
        # Add episode navigation for podcasts as row 3
        rows.append(ActionRow(
            Button(style=ButtonStyle.PRIMARY, label="Prior Episode", custom_id='previous_episode_button'),
            Button(style=ButtonStyle.PRIMARY, label="Next Episode", custom_id='next_episode_button')
        ))
    else:
        # If no chapters, add longer time jumps as row 3
        rows.append(ActionRow(
            Button(style=ButtonStyle.PRIMARY, label="-5m", custom_id='rewind_5m_button'),
            Button(style=ButtonStyle.PRIMARY, label="+5m", custom_id='forward_5m_button')
        ))

    # Add series navigation if applicable
    if is_series:
        rows.append(
            ActionRow(
                Button(disabled=is_first_in_series, style=ButtonStyle.PRIMARY, label="Prior Book", custom_id="previous_book_button"),
                Button(disabled=is_last_in_series, style=ButtonStyle.PRIMARY, label="Next Book", custom_id="next_book_button")
            )
        )
    
    return rows

# --- Embeds ---

def create_playback_embed(book_title, chapter_title, progress, current_time, duration, 
                           username, user_type, cover_image, color, volume, timestamp, version):
    embed = Embed(
        title=book_title,
        description=f"Currently playing {book_title}",
        color=color
    )

    user_info = f"Username: **{username}**\nUser Type: **{user_type}**"
    embed.add_field(name='ABS Information', value=user_info)

    # Only include chapter info if it exists
    chapter_info = f"Current Chapter: **{chapter_title}**\n" if chapter_title else ""

    playback_info = (
        f"Current State: **PLAYING**\n"
        f"Progress: **{progress}**\n"
        f"Current Time: **{current_time}**\n"
        f"{chapter_info}"
        f"Book Duration: **{duration}**\n"
        f"Current volume: **{round(volume * 100)}%**"
    )
    embed.add_field(name='Playback Information', value=playback_info)

    embed.add_image(cover_image)
    embed.footer = f"Powered by Bookshelf Traveller 🕮 | {version}\nDisplay Last Updated: {timestamp}"

    return embed

def create_book_info_embed(title, author, series, description, cover_url, color, additional_info=None):
    embed = Embed(title=title, description=description, color=color)
    embed.add_field(name="Author", value=author, inline=False)
    if series:
        embed.add_field(name="Series", value=series, inline=False)
    if additional_info:
        embed.add_field(name="Details", value=additional_info, inline=False)
    embed.add_image(cover_url)
    embed.footer = "Powered by Bookshelf Traveller 🕮"
    return embed

# --- Common Buttons ---

def get_confirmation_buttons(confirm_id="confirm_button", cancel_id="cancel_button"):
    return ActionRow(
        Button(style=ButtonStyle.SUCCESS, label="Confirm", custom_id=confirm_id),
        Button(style=ButtonStyle.DANGER, label="Cancel", custom_id=cancel_id)
    )

def get_wishlist_buttons(request_id="request_button", cancel_id="cancel_button"):
    return ActionRow(
        Button(style=ButtonStyle.PRIMARY, label="Request", custom_id=request_id),
        Button(style=ButtonStyle.SECONDARY, label="Cancel", custom_id=cancel_id)
    )
