# app.py

from __future__ import annotations

import functools
import sys
import typing
from typing import Callable
from typing import Iterable
from typing import Optional

from httpx import URL

from twitch.player import StreamLink
from twitch.utils import helpers
from twitch.utils.executor import Executor
from twitch.utils.logger import get_logger

if typing.TYPE_CHECKING:
    from twitch.datatypes import BroadcasterInfo
    from twitch.datatypes import ChannelUserFollows
    from twitch.datatypes import MenuOptions
    from twitch.datatypes import TwitchClip
    from twitch.datatypes import TwitchClips
    from twitch.twitch import TwitchClient
    from twitch.utils.menu import Menu

log = get_logger(__name__)


class App:
    """
    This class is responsible for handling the main application flow,
    including the interaction with the user through a command line interface,
    and performing requests to the Twitch API through the `TwitchClient` object.
    """

    def __init__(self, twitch: TwitchClient, menu: Menu) -> None:
        """
        Initializes the app with the specified client, menu, and execution options.
        """
        self.twitch = twitch
        self.menu = menu
        self._executor = Executor()
        self._user_follows: Optional[Iterable[ChannelUserFollows]] = None
        self.tv = URL("https://www.twitch.tv/")
        self.player = StreamLink()

    @property
    def user_follows(self) -> Iterable[ChannelUserFollows]:
        if not self._user_follows:
            self._user_follows = self.twitch.channels.follows
            return self._user_follows
        return self._user_follows

    def play_stream_selected(self, stream: str) -> None:
        url = self.tv.join(stream)
        log_msg = f"[yellow]Opening[/] [red bold]{stream}[/] with [green]{self.player.name}[/]"
        log.info("%s", log_msg)
        self._executor.notification(f"Opening stream <b>{stream}</b>")
        self.player.play(url)

    def play_clip_selected(self, clip: TwitchClip) -> None:
        """Load a selected clip by its URL."""
        log_msg = f"[yellow]Opening[/] clip [red bold]{clip.title[:40]}...[/] with [green]{self.player.name}[/]"
        log.info("%s", log_msg)
        self._executor.notification(f"Opening clip <b>{clip.broadcaster_name}@{clip.title}</b>")
        self._executor.launch(clip.url)

    def show_items(
        self,
        items: list[str],
        fallback_fn: Optional[Callable] = None,
        prompt: str = "twitch:",
        back: bool = False,
        **kwargs,
    ) -> str:
        selected = self.menu.show_items(
            self._executor,
            items,
            prompt=prompt,
            back=back,
            **kwargs,
        )

        if selected not in items:
            self.handle_missing_option(selected)
            if fallback_fn:
                fallback_fn()
            sys.exit(1)

        if selected == self.menu.back and fallback_fn is not None:
            fallback_fn()

        return selected

    def handle_missing_option(self, selected: str) -> None:
        msg_log = "Option [bold yellow]%s[/] not found."
        log.warning(msg_log, selected)
        self.show_items([f"Option '{selected}' selected not found."])

    def show_no_results_message(self, log_msg: str) -> None:
        log.warning(log_msg)
        self.menu.show_items(self._executor, [log_msg])

    def show_online_follows(self) -> None:
        """
        Show the channels that the user follows that are currently live.
        """
        items = {channel.user_name: channel for channel in self.twitch.channels_live_for_menu}
        if not items:
            self.show_no_results_message("No online followed channels")
            return

        options = list(items.keys())
        selected = self.show_items(items=options, fallback_fn=self.show_menu, prompt="'twitch live:'", back=True)

        selected = helpers.clean_string(selected, self.twitch.live_icon).split(self.twitch.delimiter)[0]
        self.play_stream_selected(selected.strip())
        return

    def show_follows_and_online(self) -> None:
        """
        Shows a list of channels that the user follows and highlights those who are live.
        """
        follow = self.show_follows()
        return self.show_info(follow.to_id)

    def show_follows(self) -> ChannelUserFollows:
        """Shows a list of channels that the user follows."""
        follows = {user.to_name: user for user in self.user_follows}
        follows_names = list(follows.keys())
        follows_names = self.merge_with_online(sorted(follows_names))

        selected = self.show_items(
            follows_names,
            fallback_fn=self.show_menu,
            prompt="'twitch follows:'",
            back=True,
            mesg=f"{self.menu.unicode.BULLET_ICON} Offline and Online channels",
        )

        if self.twitch.live_icon in selected:
            selected = selected.split(" ")[1]
            return follows[selected]
        return follows[selected]

    def merge_with_online(self, follows_names: list[str]) -> list[str]:
        delimiter = self.twitch.delimiter
        eye = self.menu.unicode.EYE
        live = self.twitch.live_icon

        for c in self.twitch.channels.followed_streams_live:
            if c.user_name in follows_names:
                # live_icon user_name title - live: viewer_count
                live_since = helpers.calculate_live_time(c.started_at)
                title = f"{live} {c.user_name} {delimiter} {c.title[:40]}"
                info = f"({eye}{c.viewer_count} viewers {delimiter} {live_since})"
                idx = follows_names.index(c.user_name)
                follows_names[idx] = f"{title} {info}"
        return follows_names

    def show_videos(self, channel: BroadcasterInfo) -> None:
        # FIX: Fix this mess..
        """Shows a list of videos for the specified channel."""
        channel_videos = self.twitch.channels.get_videos(user_id=channel.broadcaster_id)

        bullet = self.menu.unicode.BULLET_ICON
        clock = self.menu.unicode.CLOCK
        eye = self.menu.unicode.EYE
        delimiter = self.twitch.delimiter

        videos_dict = {
            f"{i} {bullet} {v.title[:50]} {delimiter} {clock}{v.duration} ({eye}{v.view_count} views)": v
            for i, v in enumerate(channel_videos)
        }

        if not videos_dict:
            self.show_no_results_message(f"No available videos from followed channel: {channel.broadcaster_name}")
            return self.show_info(channel.broadcaster_id)

        selected = self.show_items(
            list(videos_dict.keys()),
            fallback_fn=functools.partial(self.show_info, channel.broadcaster_id),
            prompt=f"'{channel.broadcaster_name} videos:'",
            back=True,
            mesg=f"Showing {len(videos_dict)} videos",
        )

        video = videos_dict[selected]
        self.play_stream_selected(video.url)
        return self.show_videos(channel)

    def show_menu(self) -> None:
        """
        Displays the main menu of the app, with options to view online channels
        and channels that the user follows.
        """
        menu_options: MenuOptions = {
            f"{self.menu.unicode.BULLET_ICON} All follows": self.show_follows_and_online,
            f"{self.menu.unicode.BULLET_ICON} Live followed": self.show_online_follows,
        }
        options_keys = list(menu_options.keys())
        selected = self.show_items(items=options_keys)
        menu_options[selected]()

    def show_info(self, user_id: str) -> None:
        """
        Shows information about a specific channel, including the channel's name, status, game being played,
        and a menu to view the channel's videos or schedule.

        Args:
        user_id (str): The ID of the channel to display information for.

        Returns:
        None: The selected option is executed.
        """
        channel = self.twitch.channels.information(user_id)

        menu_info = []
        category = f"Category: {channel.game_name}"
        menu_info.append(category)
        if self.twitch.channels.is_online(user_id):
            menu_info.append(f"{self.twitch.live_icon} Live Stream: {channel.title}")
        else:
            menu_info.append(f"Last Stream: {channel.title}")
        menu_info.append("-" * len(menu_info[1]))
        menu_info.append("Videos: Get videos")
        menu_info.append("Clips: Get clips")

        selected = self.show_items(
            menu_info,
            fallback_fn=self.show_follows_and_online,
            prompt=f"'{channel.broadcaster_name} info:'",
            back=True,
            mesg=f"Channel {channel.broadcaster_name} information",
        )

        if selected.startswith("Clips"):
            self.show_clips(channel)

        if selected.startswith("Videos"):
            self.show_videos(channel)

        if selected.startswith("Last"):
            raise NotImplementedError

        if selected.startswith(self.twitch.live_icon):
            self.play_stream_selected(channel.broadcaster_name)

        self.show_info(user_id)

    def debug(self, msg: str) -> None:
        return log.debug("%s", msg)

    def show_clips(
        self,
        channel: BroadcasterInfo,
        clips: Optional[TwitchClips] = None,
    ) -> None:
        # BUG: This is a mess...
        """
        Shows the list of clips for the specified user and allows the user to select a clip to play.

        Args:
        channel (BroadcasterInfo): The channel object to display clips for.

        Returns:
        None: The selected clip is played.
        """
        if not clips:
            log.debug("%s", f"Getting [green bold]clips[/] from channel [red bold]{channel.broadcaster_name}[/]")
            clips = self.twitch.clips.get_clips(channel.broadcaster_id)

        icons = self.menu.unicode
        clips_dict: dict[str, TwitchClip] = {}
        for idx, c in enumerate(clips):
            clip_title = f"{idx} {icons.BULLET_ICON} {c.title[:40]} createor: {c.creator_name}"
            clip_info = f"({icons.EYE}{c.view_count} views {self.twitch.delimiter} {icons.CALENDAR} {c.created_at})"
            clips_dict[f"{clip_title} {clip_info}"] = c

        if not clips_dict:
            self.show_no_results_message(f"No available clips from followed channel: {channel.broadcaster_name}")
            self.show_info(channel.broadcaster_id)

        selected = self.show_items(
            items=list(clips_dict.keys()),
            fallback_fn=functools.partial(self.show_info, channel.broadcaster_id),
            prompt=f"'{channel.broadcaster_name} clips:'",
            back=True,
            mesg=f"Showing {len(clips_dict)} clips",
        )

        clip = clips_dict[selected]
        self.play_clip_selected(clip)
        self.show_clips(channel, list(clips_dict.values()))
