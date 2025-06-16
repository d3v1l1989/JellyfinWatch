import discord
from discord.ext import commands, tasks
import requests
import time
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from discord import app_commands
from main import is_authorized
import asyncio
import aiohttp

# Library name to emoji mapping with priority order
LIBRARY_EMOJIS = {
    # Anime and Cartoons (highest priority)
    "anime": "🎌",
    "anime movies": "🎌",
    "anime series": "🎌",
    "japanese": "🎌",
    "manga": "🎌",
    "cartoons": "🎌",
    "animation": "🎌",
    
    # Movies and Films
    "movies": "🎬",
    "movie": "🎬",
    "films": "🎬",
    "cinema": "🎬",
    "feature": "🎬",
    
    # TV Shows and Series
    "tv": "📺",
    "television": "📺",
    "shows": "📺",
    "series": "📺",
    "episodes": "📺",
    "seasons": "📺",
    
    # Documentaries
    "documentaries": "📽️",
    "docs": "📽️",
    "documentary": "📽️",
    "educational": "📽️",
    "learning": "📽️",
    "science": "🔬",
    "history": "📜",
    "nature": "🌿",
    "wildlife": "🦁",
    
    # Music
    "music": "🎵",
    "songs": "🎵",
    "albums": "🎵",
    "artists": "🎵",
    "playlists": "🎵",
    "audio": "🎵",
    "concerts": "🎤",
    "live": "🎤",
    
    # Books and Audiobooks
    "books": "📚",
    "audiobooks": "📚",
    "literature": "📚",
    "reading": "📚",
    "novels": "📚",
    
    # Photos and Images
    "photos": "📸",
    "pictures": "📸",
    "images": "📸",
    "photography": "📸",
    "gallery": "📸",
    
    # Home Videos
    "home videos": "🎥",
    "videos": "🎥",
    "recordings": "🎥",
    "family videos": "🎥",
    "personal": "🎥",
    
    # Kids and Family
    "kids": "👶",
    "children": "👶",
    "family": "👶",
    "kids movies": "👶",
    "kids shows": "👶",
    "family movies": "👶",
    
    # Sports
    "sports": "⚽",
    "football": "⚽",
    "soccer": "⚽",
    "basketball": "🏀",
    "baseball": "⚾",
    "tennis": "🎾",
    "golf": "⛳",
    "racing": "🏎️",
    "olympics": "🏅",
    "matches": "⚽",
    "games": "🎮",
    
    # Foreign Content
    "foreign": "🌍",
    "international": "🌍",
    "world": "🌍",
    
    # Korean Content
    "korean": "🇰🇷",
    "korea": "🇰🇷",
    "k-drama": "🇰🇷",
    "kdrama": "🇰🇷",
    "kpop": "🇰🇷",
    
    # German Content
    "german": "🇩🇪",
    "deutsch": "🇩🇪",
    "germany": "🇩🇪",
    
    # French Content
    "french": "🇫🇷",
    "france": "🇫🇷",
    "français": "🇫🇷",
    
    # Additional Categories
    "comedy": "😂",
    "standup": "😂",
    "horror": "👻",
    "thriller": "🔪",
    "action": "💥",
    "adventure": "🗺️",
    "drama": "🎭",
    "romance": "💕",
    "scifi": "🚀",
    "fantasy": "🧙",
    "classic": "🎭",
    "indie": "🎨",
    "bollywood": "🎭",
    "hollywood": "🎬",
    "4k": "📺",
    "uhd": "📺",
    "hdr": "📺",
    "dolby": "🎵",
    "atmos": "🎵",
    
    # Default fallback
    "default": "📁"
}

# Generic terms to ignore when more specific content is found
GENERIC_TERMS = {"movies", "movie", "films", "shows", "series", "tv", "television", "videos"}

RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not RUNNING_IN_DOCKER:
    load_dotenv()

class JellyfinCore(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("jellywatch_bot.jellyfin")

        # Load environment variables
        self.JELLYFIN_URL = os.getenv("JELLYFIN_URL")
        self.JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
        self.JELLYFIN_USERNAME = os.getenv("JELLYFIN_USERNAME")
        self.JELLYFIN_PASSWORD = os.getenv("JELLYFIN_PASSWORD")
        channel_id = os.getenv("CHANNEL_ID")
        if channel_id is None:
            self.logger.error("CHANNEL_ID not set in .env file")
            raise ValueError("CHANNEL_ID must be set in .env")
        self.CHANNEL_ID = int(channel_id)

        # File paths
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.MESSAGE_ID_FILE = os.path.join(self.current_dir, "..", "data", "dashboard_message_id.json")
        self.USER_MAPPING_FILE = os.path.join(self.current_dir, "..", "data", "user_mapping.json")
        self.CONFIG_FILE = os.path.join(self.current_dir, "..", "data", "config.json")

        # Initialize state
        self.config = self._load_config()
        self.jellyfin_start_time: Optional[float] = None
        self.dashboard_message_id = self._load_message_id()
        self.last_scan = datetime.now()
        self.offline_since: Optional[datetime] = None
        self.stream_debug = False

        # Cache settings
        self.library_cache: Dict[str, Dict[str, Any]] = {}
        self.last_library_update: Optional[datetime] = None
        self.library_update_interval = self.config.get("cache", {}).get("library_update_interval", 900)

        self.user_mapping = self._load_user_mapping()
        self.update_status.start()
        self.update_dashboard.start()

    def _format_size(self, size_bytes: int) -> str:
        """Convert bytes to a human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from config.json with defaults if unavailable."""
        default_config = {
            "dashboard": {"name": "Jellyfin Dashboard", "icon_url": "", "footer_icon_url": ""},
            "jellyfin_sections": {"show_all": 1, "sections": {}},
            "presence": {
                "sections": [],
                "offline_text": "🔴 Server Offline!",
                "stream_text": "{count} active Stream{s} 🟢",
            },
            "cache": {"library_update_interval": 900},
        }
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # Convert any boolean values to integers
                if "jellyfin_sections" in config:
                    if "show_all" in config["jellyfin_sections"]:
                        config["jellyfin_sections"]["show_all"] = int(config["jellyfin_sections"]["show_all"])
                    if "sections" in config["jellyfin_sections"]:
                        for section in config["jellyfin_sections"]["sections"].values():
                            if "show_episodes" in section:
                                section["show_episodes"] = int(section["show_episodes"])
                return {**default_config, **config}  # Merge with defaults
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load config: {e}. Using defaults.")
            return default_config

    def _load_message_id(self) -> Optional[int]:
        """Load the dashboard message ID from file."""
        if not os.path.exists(self.MESSAGE_ID_FILE):
            return None
        try:
            with open(self.MESSAGE_ID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return int(data.get("message_id"))
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"Failed to load message ID: {e}")
            return None

    def _save_message_id(self, message_id: int) -> None:
        """Save the dashboard message ID to file."""
        try:
            with open(self.MESSAGE_ID_FILE, "w", encoding="utf-8") as f:
                json.dump({"message_id": message_id}, f)
        except OSError as e:
            self.logger.error(f"Failed to save message ID: {e}")

    def _load_user_mapping(self) -> Dict[str, str]:
        """Load user mapping from JSON file."""
        try:
            with open(self.USER_MAPPING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load user mapping: {e}")
            return {}

    async def connect_to_jellyfin(self) -> bool:
        """Attempt to establish a connection to the Jellyfin server with timeout and retry logic."""
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Jellyfin connection attempt {attempt + 1}/{max_retries}")
                
                # Configure timeout (10s connect, 30s total)
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                
                # Common headers for all requests
                headers = {
                    "X-Emby-Client": "JellyWatch",
                    "X-Emby-Client-Version": "1.0.0",
                    "X-Emby-Device-Name": "JellyWatch",
                    "X-Emby-Device-Id": "jellywatch-bot",
                    "Accept": "application/json",
                    "X-Emby-Authorization": "MediaBrowser Client=\"JellyWatch\", Device=\"JellyWatch\", DeviceId=\"jellywatch-bot\", Version=\"1.0.0\""
                }

                # First try with API key if available
                if self.JELLYFIN_API_KEY:
                    headers["X-Emby-Token"] = self.JELLYFIN_API_KEY
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(f"{self.JELLYFIN_URL}/System/Info", headers=headers) as response:
                            if response.status == 200:
                                self.logger.info("Successfully connected to Jellyfin with API key")
                                if self.jellyfin_start_time is None:
                                    self.jellyfin_start_time = time.time()
                                return True
                            elif response.status == 401:
                                self.logger.error("Invalid API key provided")
                                return False
                            else:
                                self.logger.warning(f"Failed to connect with API key: HTTP {response.status}")
                                if attempt == max_retries - 1:
                                    return False

                # If API key fails or not available, try username/password
                if self.JELLYFIN_USERNAME and self.JELLYFIN_PASSWORD:
                    auth_data = {
                        "Username": self.JELLYFIN_USERNAME,
                        "Pw": self.JELLYFIN_PASSWORD
                    }
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.post(
                            f"{self.JELLYFIN_URL}/Users/AuthenticateByName",
                            json=auth_data,
                            headers=headers
                        ) as response:
                            if response.status == 200:
                                self.logger.info("Successfully connected to Jellyfin with username/password")
                                if self.jellyfin_start_time is None:
                                    self.jellyfin_start_time = time.time()
                                return True
                            elif response.status == 401:
                                self.logger.error("Invalid username or password")
                                return False
                            else:
                                self.logger.warning(f"Failed to authenticate with username/password: HTTP {response.status}")
                                if attempt == max_retries - 1:
                                    return False

                if attempt == max_retries - 1:
                    self.logger.error("No authentication method provided (API key or username/password required)")
                    return False
                    
            except asyncio.TimeoutError:
                self.logger.warning(f"Connection timeout on attempt {attempt + 1}/{max_retries}")
                if attempt == max_retries - 1:
                    self.logger.error("Failed to connect to Jellyfin: Connection timeout after all retries")
                    self.jellyfin_start_time = None
                    return False
            except aiohttp.ClientConnectorError as e:
                self.logger.warning(f"Connection error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt == max_retries - 1:
                    self.logger.error(f"Failed to connect to Jellyfin: Connection error after all retries: {e}")
                    self.jellyfin_start_time = None
                    return False
            except Exception as e:
                self.logger.warning(f"Unexpected error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt == max_retries - 1:
                    self.logger.error(f"Failed to connect to Jellyfin: Unexpected error after all retries: {e}")
                    self.jellyfin_start_time = None
                    return False
            
            # Exponential backoff for retries
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                self.logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
        
        return False

    @tasks.loop(seconds=30)
    async def update_status(self) -> None:
        """Update bot's status with current stream count."""
        try:
            sessions = await self.get_sessions()
            current_streams = len(sessions) if sessions else 0
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{current_streams} stream{'s' if current_streams != 1 else ''}"
            )
            await self.bot.change_presence(activity=activity)
        except Exception as e:
            self.logger.error(f"Error updating status: {e}")

    @tasks.loop(seconds=60)
    async def update_dashboard(self) -> None:
        """Update the dashboard message periodically."""
        try:
            self.logger.info(f"Dashboard update starting - Channel ID: {self.CHANNEL_ID}")
            self.logger.info(f"Dashboard message ID: {self.dashboard_message_id}")
            
            info = await self.get_server_info()
            if not info:
                self.logger.warning("No server info received - Jellyfin may be unreachable")
                return

            channel = self.bot.get_channel(self.CHANNEL_ID)
            if not channel:
                self.logger.error("Dashboard channel not found")
                return

            self.logger.info(f"Creating dashboard embed with info keys: {list(info.keys())}")
            embed = await self.create_dashboard_embed(info)
            await self._update_dashboard_message(channel, embed)
            self.logger.info("Dashboard update completed successfully")
        except Exception as e:
            self.logger.error(f"Error updating dashboard: {e}", exc_info=True)

    async def get_server_info(self) -> Dict[str, Any]:
        """Get server information from Jellyfin."""
        try:
            self.logger.info("Attempting to connect to Jellyfin...")
            if not await self.connect_to_jellyfin():
                self.logger.error("Failed to connect to Jellyfin server")
                return {}

            headers = {
                "X-Emby-Token": self.JELLYFIN_API_KEY,
                "X-Emby-Client": "JellyWatch",
                "X-Emby-Client-Version": "1.0.0",
                "X-Emby-Device-Name": "JellyWatch",
                "X-Emby-Device-Id": "jellywatch-bot",
                "Accept": "application/json",
                "X-Emby-Authorization": "MediaBrowser Client=\"JellyWatch\", Device=\"JellyWatch\", DeviceId=\"jellywatch-bot\", Version=\"1.0.0\""
            }

            # Configure timeout for all requests
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Get system info
                async with session.get(f"{self.JELLYFIN_URL}/System/Info", headers=headers) as response:
                    if response.status != 200:
                        self.logger.error(f"Failed to get system info: HTTP {response.status}")
                        return {}
                    system_info = await response.json()
                
                # Get sessions
                sessions = await self.get_sessions()
                current_streams = len([s for s in sessions if s.get("NowPlayingItem")]) if sessions else 0

                # Get library stats
                library_stats = await self.get_library_stats()
                total_items = sum(int(stats.get("count", 0)) for stats in library_stats.values())
                total_episodes = sum(int(episodes) for stats in library_stats.values() 
                                   if (episodes := stats.get("episodes")) is not None)

                return {
                    "server_name": system_info.get("ServerName", "Unknown Server"),
                    "version": system_info.get("Version", "Unknown Version"),
                    "operating_system": system_info.get("OperatingSystem", "Unknown OS"),
                    "current_streams": current_streams,
                    "total_items": total_items,
                    "total_episodes": total_episodes,
                    "library_stats": library_stats
                }
        except Exception as e:
            self.logger.error(f"Error getting server info: {e}")
            return {}

    def calculate_uptime(self) -> str:
        """Calculate Jellyfin server uptime as a formatted string."""
        if not self.jellyfin_start_time:
            return "Offline"
        total_minutes = int((time.time() - self.jellyfin_start_time) / 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return "99+ Hours" if hours > 99 else f"{hours:02d}:{minutes:02d}"

    async def get_library_stats(self) -> Dict[str, Dict[str, Any]]:
        """Fetch and cache Jellyfin library statistics."""
        current_time = datetime.now()
        if (
            self.last_library_update
            and (current_time - self.last_library_update).total_seconds() <= self.library_update_interval
        ):
            return self.library_cache

        if not await self.connect_to_jellyfin():
            return self.library_cache

        try:
            headers = {
                "X-Emby-Token": self.JELLYFIN_API_KEY,
                "X-Emby-Client": "JellyWatch",
                "X-Emby-Client-Version": "1.0.0",
                "X-Emby-Device-Name": "JellyWatch",
                "X-Emby-Device-Id": "jellywatch-bot",
                "Accept": "application/json",
                "X-Emby-Authorization": "MediaBrowser Client=\"JellyWatch\", Device=\"JellyWatch\", DeviceId=\"jellywatch-bot\", Version=\"1.0.0\""
            }
            
            # Configure timeout for all requests (longer for library stats due to potentially large libraries)
            timeout = aiohttp.ClientTimeout(total=60, connect=10)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Get all libraries
                async with session.get(f"{self.JELLYFIN_URL}/Library/VirtualFolders", headers=headers) as response:
                    if response.status != 200:
                        self.logger.error(f"Failed to get library folders: HTTP {response.status}")
                        return self.library_cache
                    libraries = await response.json()

                stats: Dict[str, Dict[str, Any]] = {}
                jellyfin_config = self.config["jellyfin_sections"]
                configured_sections = jellyfin_config["sections"]

                for library in libraries:
                    library_id = library.get("ItemId")
                    library_name = library.get("Name", "").lower()
                    
                    if not int(jellyfin_config["show_all"]) and library_id not in configured_sections:
                        continue

                    # Get library configuration
                    config = configured_sections.get(library_id, {
                        "display_name": library.get("Name", "Unknown Library"),
                        "emoji": LIBRARY_EMOJIS["default"],
                        "show_episodes": 0
                    })

                    # Use the configured emoji directly
                    emoji = config.get("emoji", LIBRARY_EMOJIS["default"])

                    # Get item counts using more efficient separate queries to avoid timeouts
                    movie_count = 0
                    series_count = 0
                    episode_count = 0
                    
                    # Count movies
                    movie_params = {
                        "ParentId": library_id,
                        "Recursive": "true",
                        "IncludeItemTypes": "Movie",
                        "Fields": "",
                        "Limit": 1,
                        "EnableTotalRecordCount": "true"
                    }
                    try:
                        async with session.get(
                            f"{self.JELLYFIN_URL}/Items",
                            headers=headers,
                            params=movie_params
                        ) as movie_response:
                            if movie_response.status == 200:
                                movie_data = await movie_response.json()
                                movie_count = movie_data.get("TotalRecordCount", 0)
                    except Exception as e:
                        self.logger.warning(f"Failed to get movie count for {library_name}: {e}")
                    
                    # Count series
                    series_params = {
                        "ParentId": library_id,
                        "Recursive": "true",
                        "IncludeItemTypes": "Series",
                        "Fields": "",
                        "Limit": 1,
                        "EnableTotalRecordCount": "true"
                    }
                    try:
                        async with session.get(
                            f"{self.JELLYFIN_URL}/Items",
                            headers=headers,
                            params=series_params
                        ) as series_response:
                            if series_response.status == 200:
                                series_data = await series_response.json()
                                series_count = series_data.get("TotalRecordCount", 0)
                    except Exception as e:
                        self.logger.warning(f"Failed to get series count for {library_name}: {e}")
                    
                    # Count episodes only if needed
                    if config.get("show_episodes", 0):
                        episode_params = {
                            "ParentId": library_id,
                            "Recursive": "true",
                            "IncludeItemTypes": "Episode",
                            "Fields": "",
                            "Limit": 1,
                            "EnableTotalRecordCount": "true"
                        }
                        try:
                            async with session.get(
                                f"{self.JELLYFIN_URL}/Items",
                                headers=headers,
                                params=episode_params
                            ) as episode_response:
                                if episode_response.status == 200:
                                    episode_data = await episode_response.json()
                                    episode_count = episode_data.get("TotalRecordCount", 0)
                        except Exception as e:
                            self.logger.warning(f"Failed to get episode count for {library_name}: {e}")

                            # Create base stats dictionary
                            library_stats = {
                                "count": movie_count + series_count,
                                "display_name": config.get("display_name", library.get("Name", "Unknown Library")),
                                "emoji": emoji,
                                "show_episodes": int(config.get("show_episodes", 0))  # Ensure integer
                            }

                            # Only add episodes if show_episodes is 1
                            if int(config.get("show_episodes", 0)) == 1:
                                library_stats["episodes"] = episode_count

                            stats[library_id] = library_stats
                        else:
                            # Get the response body for more detailed error information
                            error_body = await items_response.text()
                            self.logger.error(f"Failed to get items for library {library_name}: HTTP {items_response.status}")
                            self.logger.error(f"Error response body: {error_body}")
                            self.logger.error(f"Request URL: {items_response.url}")
                            self.logger.error(f"Request headers: {headers}")
                            self.logger.error(f"Request params: {params}")

            self.library_cache = stats
            self.last_library_update = current_time
            self.logger.info(f"Library stats updated and cached (interval: {self.library_update_interval}s)")
            return stats
        except Exception as e:
            self.logger.error(f"Error updating library stats: {e}", exc_info=True)
            return self.library_cache

    async def get_sessions(self) -> List[Dict[str, Any]]:
        """Get current Jellyfin sessions."""
        if not await self.connect_to_jellyfin():
            return []

        try:
            headers = {
                "X-Emby-Token": self.JELLYFIN_API_KEY,
                "X-Emby-Client": "JellyWatch",
                "X-Emby-Client-Version": "1.0.0",
                "X-Emby-Device-Name": "JellyWatch",
                "X-Emby-Device-Id": "jellywatch-bot",
                "Accept": "application/json",
                "X-Emby-Authorization": "MediaBrowser Client=\"JellyWatch\", Device=\"JellyWatch\", DeviceId=\"jellywatch-bot\", Version=\"1.0.0\""
            }
            
            # Configure timeout for all requests
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.JELLYFIN_URL}/Sessions", headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 401:
                        self.logger.error("Invalid API key when fetching sessions")
                        return []
                    else:
                        self.logger.error(f"Failed to get sessions: HTTP {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error getting sessions: {e}")
            return []

    def get_active_streams(self) -> List[str]:
        """Retrieve formatted information about active Jellyfin streams."""
        sessions = self.get_sessions()
        if self.stream_debug:
            self.logger.debug(f"Found {len(sessions)} active sessions")
        
        active_streams = []
        for idx, session in enumerate(sessions, start=1):
            if session.get("NowPlayingItem"):
                stream_info = self.format_stream_info(session, idx)
                if stream_info:
                    active_streams.append(stream_info)
                    if self.stream_debug:
                        self.logger.debug(f"Formatted Stream Info:\n{stream_info}\n{'='*50}")
        
        return active_streams

    def format_stream_info(self, session: Dict[str, Any], idx: int) -> str:
        """Format Jellyfin session information into a readable string."""
        try:
            item = session["NowPlayingItem"]
            user = session.get("UserName", "Unknown")
            player = session.get("Client", "Unknown")
            
            # Get progress percentage
            position_ticks = session.get("PlayState", {}).get("PositionTicks", 0)
            runtime_ticks = item.get("RunTimeTicks", 0)
            progress = (position_ticks / runtime_ticks * 100) if runtime_ticks else 0
            
            # Format title
            title = self._get_formatted_title(item)
            
            # Get quality info
            quality = "Unknown"
            if "MediaStreams" in item:
                for stream in item["MediaStreams"]:
                    if stream.get("Type") == "Video":
                        quality = f"{stream.get('Width', '?')}x{stream.get('Height', '?')}"
                        break
            
            # Format stream info
            stream_info = (
                f"**{idx}. {title}**\n"
                f"📱 {player}\n"
                f"📊 {progress:.1f}% | {quality}"
            )
            
            return stream_info
        except Exception as e:
            self.logger.error(f"Error formatting stream info: {e}")
            return ""

    def _get_formatted_title(self, item: Dict[str, Any]) -> str:
        """Format the title of a Jellyfin item."""
        try:
            if item["Type"] == "Episode":
                series_name = item.get("SeriesName", "Unknown Series")
                season_episode = f"S{item.get('ParentIndexNumber', 0):02d}E{item.get('IndexNumber', 0):02d}"
                episode_name = item.get("Name", "Unknown Episode")
                return f"{series_name} - {season_episode} - {episode_name}"
            else:
                return item.get("Name", "Unknown")
        except Exception as e:
            self.logger.error(f"Error formatting title: {e}")
            return "Unknown"

    def get_offline_info(self) -> Dict[str, Any]:
        """Return offline status information."""
        if self.offline_since is None:
            self.offline_since = datetime.now()
        
        offline_duration = datetime.now() - self.offline_since
        hours = int(offline_duration.total_seconds() / 3600)
        minutes = int((offline_duration.total_seconds() % 3600) / 60)
        
        # Convert any boolean values in library_cache to integers
        library_stats = {}
        for library_id, stats in self.library_cache.items():
            library_stats[library_id] = {
                "count": int(stats.get("count", 0)),
                "display_name": stats.get("display_name", "Unknown Library"),
                "emoji": stats.get("emoji", "📁"),
                "show_episodes": int(stats.get("show_episodes", 0))
            }
            if "episodes" in stats:
                library_stats[library_id]["episodes"] = int(stats["episodes"])
        
        return {
            "status": "🔴 Offline",
            "uptime": f"Offline for {hours:02d}:{minutes:02d}",
            "library_stats": library_stats,
            "active_users": [],
            "current_streams": [],
        }

    async def create_dashboard_embed(self, info: Dict[str, Any]) -> discord.Embed:
        """Create the dashboard embed with server information."""
        embed = discord.Embed(
            title=f"📺 {info.get('server_name', 'Jellyfin Server')}",
            description="Real-time server status and statistics",
            color=discord.Color.blue()
        )
        
        # Set thumbnail to Jellyfin logo (512x512 version)
        embed.set_thumbnail(url="https://static-00.iconduck.com/assets.00/jellyfin-icon-512x512-jcuy5qbi.png")
        
        # Add server status
        status = "🟢 Online" if info else "🔴 Offline"
        uptime = self.calculate_uptime()
        embed.add_field(
            name="Server Status",
            value=f"{status}\nUptime: {uptime}",
            inline=False
        )
        
        # Add active streams
        current_streams = info.get('current_streams', 0)
        embed.add_field(
            name="Active Streams",
            value=f"```css\n{current_streams} active stream{'s' if current_streams != 1 else ''}\n```",
            inline=False
        )
        
        # Add library statistics
        library_stats = info.get('library_stats', {})
        if library_stats:
            # Sort libraries by display_name
            sorted_libraries = sorted(
                library_stats.items(),
                key=lambda x: x[1].get('display_name', '').lower()
            )
            
            stats_text = ""
            for library_id, stats in sorted_libraries:
                if stats.get('count', 0) > 0:  # Only show libraries with items
                    stats_text += f"{stats.get('emoji', '📁')} **{stats.get('display_name', 'Unknown Library')}**\n"
                    stats_text += f"```css\nTotal Items: {stats.get('count', 0)}\n```\n"
                    # Only show episodes if show_episodes is 1 and episodes count exists
                    if int(stats.get('show_episodes', 0)) == 1 and 'episodes' in stats:
                        stats_text += f"```css\nEpisodes: {stats['episodes']}\n```\n"
            if stats_text:  # Only add the field if there are libraries to show
                embed.add_field(
                    name="Library Statistics",
                    value=stats_text,
                    inline=False
                )
        
        # Set footer with JellyfinWatch branding and timestamp
        current_time = datetime.now().strftime("%H:%M:%S")
        embed.set_footer(
            text=f"Powered by JellyfinWatch | Last updated at {current_time}",
            icon_url="https://static-00.iconduck.com/assets.00/jellyfin-icon-96x96-h2vkd1yr.png"
        )
        
        return embed

    async def _update_dashboard_message(self, channel: discord.TextChannel, embed: discord.Embed) -> None:
        """Update or create the dashboard message with improved rate limiting."""
        max_retries = 3
        base_delay = 1
        
        try:
            if not channel:
                self.logger.error("Dashboard channel not found")
                return

            if self.dashboard_message_id:
                self.logger.info(f"Attempting to edit existing message ID: {self.dashboard_message_id}")
                
                # Try with exponential backoff for rate limiting
                for attempt in range(max_retries):
                    try:
                        message = await channel.fetch_message(self.dashboard_message_id)
                        await message.edit(embed=embed)
                        self.logger.info("Successfully edited existing dashboard message")
                        return
                    except discord.RateLimited as e:
                        if attempt == max_retries - 1:
                            self.logger.error(f"Failed to edit message after {max_retries} rate limit attempts")
                            return
                        
                        retry_delay = max(e.retry_after, base_delay * (2 ** attempt))
                        self.logger.warning(f"Rate limited on attempt {attempt + 1}/{max_retries}, waiting {retry_delay:.1f} seconds")
                        await asyncio.sleep(retry_delay)
                        continue
                    except discord.NotFound:
                        self.logger.warning(f"Dashboard message {self.dashboard_message_id} not found, will create new message")
                        self.dashboard_message_id = None
                        break  # Exit retry loop to create new message
                    except discord.Forbidden:
                        self.logger.error("Bot doesn't have permission to edit messages in the channel")
                        return
                    except discord.HTTPException as e:
                        if attempt == max_retries - 1:
                            self.logger.error(f"HTTP error editing message after {max_retries} attempts: {e}")
                            return
                        
                        delay = base_delay * (2 ** attempt)
                        self.logger.warning(f"HTTP error on attempt {attempt + 1}/{max_retries}, retrying in {delay} seconds: {e}")
                        await asyncio.sleep(delay)
                        continue
                    except Exception as e:
                        self.logger.error(f"Unexpected error editing message: {e}")
                        return

            # Create new message if we don't have an ID or message was not found
            if not self.dashboard_message_id:
                for attempt in range(max_retries):
                    try:
                        self.logger.info(f"Creating new dashboard message (attempt {attempt + 1}/{max_retries})")
                        message = await channel.send(embed=embed)
                        self.dashboard_message_id = message.id
                        self._save_message_id(message.id)
                        self.logger.info(f"Successfully created new dashboard message with ID: {message.id}")
                        return
                    except discord.RateLimited as e:
                        if attempt == max_retries - 1:
                            self.logger.error(f"Failed to create message after {max_retries} rate limit attempts")
                            return
                        
                        retry_delay = max(e.retry_after, base_delay * (2 ** attempt))
                        self.logger.warning(f"Rate limited creating message on attempt {attempt + 1}/{max_retries}, waiting {retry_delay:.1f} seconds")
                        await asyncio.sleep(retry_delay)
                        continue
                    except discord.Forbidden:
                        self.logger.error("Bot doesn't have permission to send messages in the channel")
                        return
                    except discord.HTTPException as e:
                        if attempt == max_retries - 1:
                            self.logger.error(f"HTTP error creating message after {max_retries} attempts: {e}")
                            return
                        
                        delay = base_delay * (2 ** attempt)
                        self.logger.warning(f"HTTP error creating message on attempt {attempt + 1}/{max_retries}, retrying in {delay} seconds: {e}")
                        await asyncio.sleep(delay)
                        continue
                    except Exception as e:
                        self.logger.error(f"Unexpected error creating message: {e}")
                        return
                        
        except Exception as e:
            self.logger.error(f"Error updating dashboard message: {e}", exc_info=True)

    @app_commands.command(name="update_libraries", description="Update library sections in the dashboard")
    @app_commands.check(is_authorized)
    async def update_libraries(self, interaction: discord.Interaction):
        """Update library sections in the dashboard."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not await self.connect_to_jellyfin():
                await interaction.followup.send("❌ Failed to connect to Jellyfin server.", ephemeral=True)
                return

            # Get all libraries
            headers = {
                "X-Emby-Token": self.JELLYFIN_API_KEY,
                "X-Emby-Client": "JellyWatch",
                "X-Emby-Client-Version": "1.0.0",
                "X-Emby-Device-Name": "JellyWatch",
                "X-Emby-Device-Id": "jellywatch-bot",
                "Accept": "application/json",
                "X-Emby-Authorization": "MediaBrowser Client=\"JellyWatch\", Device=\"JellyWatch\", DeviceId=\"jellywatch-bot\", Version=\"1.0.0\""
            }
            
            # Configure timeout for all requests
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.JELLYFIN_URL}/Library/VirtualFolders", headers=headers) as response:
                    if response.status != 200:
                        await interaction.followup.send("❌ Failed to fetch libraries from Jellyfin.", ephemeral=True)
                        return

                    libraries = await response.json()
            
            # Sort libraries by name
            libraries = sorted(libraries, key=lambda x: x.get("Name", "").lower())
            
            # Update config with new libraries
            self.config["jellyfin_sections"]["sections"] = {}
            
            for library in libraries:
                library_name = library.get("Name", "").lower()
                library_id = library.get("ItemId")
                
                # Find matching emoji based on library name with priority
                emoji = LIBRARY_EMOJIS["default"]
                best_match_length = 0
                best_match_key = None
                
                # First pass: find all matches
                matches = []
                library_name_lower = library_name.lower()
                for key, value in LIBRARY_EMOJIS.items():
                    if key == "default":
                        continue
                    if key in library_name_lower:
                        matches.append((key, value, len(key), key in GENERIC_TERMS))
                
                # Second pass: find the best non-generic match
                for key, value, length, is_generic in matches:
                    if not is_generic and length > best_match_length:
                        best_match_length = length
                        best_match_key = key
                        emoji = value
                
                # If no non-generic match was found, use the best match overall
                if best_match_key is None and matches:
                    best_match_length = max(length for _, _, length, _ in matches)
                    for key, value, length, _ in matches:
                        if length == best_match_length:
                            emoji = value
                            break
                
                # Log the emoji selection for debugging
                self.logger.debug(f"Library '{library_name}' matched with emoji '{emoji}' (best match: '{best_match_key}')")
                
                # Always set show_episodes to 0 by default
                show_episodes = 0
                
                self.config["jellyfin_sections"]["sections"][library_id] = {
                    "display_name": library.get("Name", "Unknown Library"),
                    "emoji": emoji,
                    "color": "#00A4DC",
                    "show_episodes": show_episodes  # Use integer instead of boolean
                }

            # Save updated config
            self.save_config()
            
            # Clear the library cache to force refresh
            self.library_cache = {}
            self.last_library_update = None
            
            # Send initial success message
            await interaction.followup.send("✅ Libraries updated successfully! Refreshing dashboard in 10 seconds...", ephemeral=True)
            
            # Wait 10 seconds
            await asyncio.sleep(10)
            
            # Get server info and update dashboard
            info = await self.get_server_info()
            channel = self.bot.get_channel(self.CHANNEL_ID)
            embed = await self.create_dashboard_embed(info)
            await self._update_dashboard_message(channel, embed)
            
        except Exception as e:
            self.logger.error(f"Error updating libraries: {e}")
            await interaction.followup.send(f"❌ Error updating libraries: {str(e)}", ephemeral=True)

    @app_commands.command(name="episodes", description="Toggle episode numbers display in the dashboard")
    @app_commands.check(is_authorized)
    async def toggle_episodes(self, interaction: discord.Interaction):
        """Toggle episode numbers display in the dashboard."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get current state from any library (they should all be the same)
            current_state = 0
            sections = self.config["jellyfin_sections"]["sections"]
            
            if not sections:
                await interaction.followup.send(
                    "⚠️ No libraries are configured yet. Please use `/update_libraries` first.",
                    ephemeral=True
                )
                return
                
            first_library = next(iter(sections.values()))
            current_state = int(first_library.get("show_episodes", 0))  # Ensure integer
            
            # Log the current state
            self.logger.info(f"Current show_episodes state: {current_state}")
            
            # Toggle the show_episodes setting for all libraries
            new_state = 1 if current_state == 0 else 0
            for library_id, library_config in sections.items():
                library_config["show_episodes"] = new_state
                self.logger.info(f"Updated library {library_id} show_episodes to {new_state}")
            
            # Save the updated config
            self.save_config()
            
            # Clear the library cache and force a refresh
            self.library_cache = {}
            self.last_library_update = None
            
            # Get server info and update dashboard
            info = await self.get_server_info()
            channel = self.bot.get_channel(self.CHANNEL_ID)
            embed = await self.create_dashboard_embed(info)
            await self._update_dashboard_message(channel, embed)
            
            await interaction.followup.send(
                f"✅ Episode numbers display has been {'enabled' if new_state == 1 else 'disabled'}!",
                ephemeral=True
            )
            
        except Exception as e:
            self.logger.error(f"Error toggling episodes display: {e}")
            await interaction.followup.send(f"❌ Error toggling episodes display: {str(e)}", ephemeral=True)

    @app_commands.command(name="refresh", description="Refresh the dashboard embed immediately")
    @app_commands.check(is_authorized)
    async def refresh_dashboard(self, interaction: discord.Interaction):
        """Refresh the dashboard embed immediately."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info("Starting dashboard refresh...")
            
            # Get server info and update dashboard
            self.logger.info("Attempting to get server info...")
            info = await self.get_server_info()
            if not info:
                self.logger.error("Failed to get server info - empty response")
                await interaction.followup.send("❌ Failed to get server information. Check bot logs for details.", ephemeral=True)
                return
                
            self.logger.info(f"Got server info: {info.get('server_name', 'Unknown Server')}")
            
            self.logger.info(f"Getting channel with ID: {self.CHANNEL_ID}")
            channel = self.bot.get_channel(self.CHANNEL_ID)
            if not channel:
                self.logger.error(f"Channel {self.CHANNEL_ID} not found")
                await interaction.followup.send("❌ Dashboard channel not found. Check CHANNEL_ID in config.", ephemeral=True)
                return
                
            self.logger.info("Creating dashboard embed...")
            embed = await self.create_dashboard_embed(info)
            
            self.logger.info("Updating dashboard message...")
            await self._update_dashboard_message(channel, embed)
            
            self.logger.info("Dashboard refresh completed successfully")
            await interaction.followup.send("✅ Dashboard refreshed successfully!", ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"Error refreshing dashboard: {str(e)}", exc_info=True)
            await interaction.followup.send(f"❌ Error refreshing dashboard: {str(e)}", ephemeral=True)

    @app_commands.command(name="sync", description="Sync slash commands with Discord")
    @app_commands.check(is_authorized)
    async def sync_commands(self, interaction: discord.Interaction):
        """Sync slash commands with Discord."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Sync the command tree
            await self.bot.tree.sync()
            await interaction.followup.send("✅ Slash commands synced successfully!", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error syncing commands: {e}")
            await interaction.followup.send(f"❌ Error syncing commands: {str(e)}", ephemeral=True)

    def load_config(self) -> Dict[str, Any]:
        """Load the configuration from config.json."""
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.error("Config file not found. Creating default config.")
            default_config = {
                "jellyfin_url": "",
                "jellyfin_api_key": "",
                "dashboard_channel_id": 0,
                "jellyfin_sections": {
                    "sections": {},
                    "show_all": 1
                }
            }
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
            return default_config
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing config file: {e}")
            raise

    def save_config(self) -> None:
        """Save the current configuration to config.json."""
        try:
            # Create a copy of the config to modify
            config_to_save = {
                "dashboard": self.config.get("dashboard", {}),
                "jellyfin_sections": {
                    "show_all": int(self.config.get("jellyfin_sections", {}).get("show_all", 1)),
                    "sections": {}
                },
                "presence": self.config.get("presence", {}),
                "cache": self.config.get("cache", {})
            }
            
            # Convert any boolean values to integers in sections
            for library_id, section in self.config.get("jellyfin_sections", {}).get("sections", {}).items():
                config_to_save["jellyfin_sections"]["sections"][library_id] = {
                    "display_name": section.get("display_name", "Unknown Library"),
                    "emoji": section.get("emoji", "📁"),
                    "color": section.get("color", "#00A4DC"),
                    "show_episodes": int(section.get("show_episodes", 0))
                }
            
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_to_save, f, indent=4)
        except Exception as e:
            self.logger.error(f"Error saving config file: {e}")
            raise

async def setup(bot: commands.Bot) -> None:
    """Add the JellyfinCore cog to the bot."""
    await bot.add_cog(JellyfinCore(bot)) 