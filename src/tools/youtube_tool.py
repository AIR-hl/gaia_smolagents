import glob
import tempfile
from typing import Optional
from smolagents import tool
import subprocess
import json
import os
import logging
from urllib.parse import urlparse, parse_qs
import textwrap
DOWNLOADS_LOADER="downloads"

logger = logging.getLogger(__name__)

@tool
def visit_ytb_page(url: str) -> str:
    """
    Parse YouTube video page in given URL, and get good structured content about it.
    You should use this tool for youtube page rather than the `visit_webpage` or `parse_file` tool.
    
    Args:
        url: The URL of the YouTube video to get information from.
    """
    try:
        cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-playlist',
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return f"Error getting video info: {result.stderr}"
        
        # Parse JSON response
        try:
            video_info = json.loads(result.stdout)
        except json.JSONDecodeError:
            return "Error: Could not parse video information"
        
        # Extract and format information
        info_result = []
        info_result.append(f"YouTube Video: {video_info.get('title', 'Unknown title')}")
        info_result.append("=" * 50)
        
        # Basic info
        info_result.append(f"Video ID: {video_info.get('id', 'Unknown')}")
        info_result.append(f"URL: {video_info.get('webpage_url', url)}")
        info_result.append(f"Duration: {video_info.get('duration_string', 'Unknown')}")
        info_result.append(f"Upload date: {video_info.get('upload_date', 'Unknown')}")
        
        # Channel info
        info_result.append(f"Channel: {video_info.get('uploader', 'Unknown')}")
        info_result.append(f"Channel ID: {video_info.get('channel_id', 'Unknown')}")
        info_result.append(f"Channel URL: {video_info.get('channel_url', 'Unknown')}")
        
        # Stats
        info_result.append(f"View count: {video_info.get('view_count', 'Unknown')}")
        info_result.append(f"Like count: {video_info.get('like_count', 'Unknown')}")
        info_result.append(f"Comment count: {video_info.get('comment_count', 'Unknown')}")
        
        # Description
        description = video_info.get('description', '')
        if description:
            # Limit description length
            if len(description) > 500:
                description = description[:500] + "..."
            info_result.append(f"\nDescription:")
            info_result.append(description)
        
        # Tags
        tags = video_info.get('tags', [])
        if tags:
            info_result.append(f"\nTags: {', '.join(tags[:10])}")
            if len(tags) > 10:
                info_result.append(f"... and {len(tags) - 10} more tags")
        
        # Categories
        categories = video_info.get('categories', [])
        if categories:
            info_result.append(f"Categories: {', '.join(categories)}")
        
        # Available formats info
        formats = video_info.get('formats', [])
        if formats:
            info_result.append(f"\nAvailable formats: {len(formats)}")
            
            # Show some format details
            video_formats = [f for f in formats if f.get('vcodec', 'none') != 'none']
            audio_formats = [f for f in formats if f.get('acodec', 'none') != 'none' and f.get('vcodec', 'none') == 'none']
            
            if video_formats:
                best_video = max(video_formats, key=lambda x: x.get('height', 0))
                info_result.append(f"Best video quality: {best_video.get('height', 'Unknown')}p")
            
            if audio_formats:
                best_audio = max(audio_formats, key=lambda x: x.get('abr', 0))
                info_result.append(f"Best audio quality: {best_audio.get('abr', 'Unknown')} kbps")
        
        # Thumbnail
        thumbnail = video_info.get('thumbnail')
        if thumbnail:
            info_result.append(f"Thumbnail: {thumbnail}")
        
        return "\n".join(info_result)
        
    except subprocess.TimeoutExpired:
        return "Error: Request timed out while getting video information"
    except Exception as e:
        return f"Error getting YouTube video info: {str(e)}"

@tool
def get_ytb_screenshot(url: str, timestamp: str) -> str:
    """Get a screenshot from a YouTube video at the specified timestamp.
    
    Args:
        url: The URL of the YouTube video to get a screenshot from.
        timestamp: The timestamp of the video to get a screenshot from. For example, "00:01:30" for the 1 minute 30 seconds mark.
    """

    try:
        downloads_dir = "downloads"
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Get video info for filename generation
        info_cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-playlist',
            url
        ]
        
        result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return f"Error getting video info: {result.stderr}"
        
        try:
            video_info = json.loads(result.stdout)
        except json.JSONDecodeError:
            return "Error: Could not parse video information"
        
        video_id = video_info.get('id', 'unknown')
        video_title = video_info.get('title', 'Unknown Video')
        
        # Generate output filename
        clean_timestamp = timestamp.replace(':', '')
        output_path = os.path.join(downloads_dir, f"{video_id}_{clean_timestamp}.jpg")
        
        # Method 1: Download video segment and extract screenshot
        def timestamp_to_seconds(ts):
            parts = ts.split(':')
            if len(parts) == 3:  # HH:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            else:
                return int(parts[0])
        
        start_seconds = timestamp_to_seconds(timestamp)
        end_seconds = start_seconds + 5  # Download 5 second segment
        
        # Create temp file
        with tempfile.NamedTemporaryFile(suffix='.%(ext)s', delete=False, dir=downloads_dir) as temp_file:
            temp_template = temp_file.name
        
        # Download video segment using yt-dlp
        download_cmd = [
            'yt-dlp',
            '--format', 'best[height<=720]',
            '--external-downloader', 'ffmpeg',
            '--external-downloader-args', f'ffmpeg_i:-ss {start_seconds} -t 5',
            '--output', temp_template,
            url
        ]
        
        download_result = subprocess.run(download_cmd, capture_output=True, text=True, timeout=120)
        
        # Find downloaded file
        downloaded_file = None
        for ext in ['mp4', 'webm', 'mkv', 'flv']:
            potential_file = temp_template.replace('.%(ext)s', f'.{ext}')
            if os.path.exists(potential_file):
                downloaded_file = potential_file
                break
        
        if downloaded_file and os.path.exists(downloaded_file):
            # Extract screenshot from video segment
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', downloaded_file,
                '-ss', '0',  # Screenshot from segment start
                '-vframes', '1',
                '-q:v', '2',
                '-y',
                output_path
            ]
            
            ffmpeg_result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=30)
            
            # Clean up temp file
            try:
                os.remove(downloaded_file)
            except:
                pass
            
            if ffmpeg_result.returncode == 0 and os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                return f"Screenshot captured successfully!\nVideo: {video_title}\nTimestamp: {timestamp}\nSaved to: {output_path}\nFile size: {file_size} bytes"
        
        # Method 2: Direct screenshot with yt-dlp + ffmpeg
        screenshot_cmd = [
            'yt-dlp',
            '--format', 'best[height<=720]',
            '--exec', f'ffmpeg -ss {timestamp} -i "{{}}" -vframes 1 -q:v 2 -y "{output_path}"',
            '--exec-before-download', f'echo "Processing video..."',
            url
        ]
        
        screenshot_result = subprocess.run(screenshot_cmd, capture_output=True, text=True, timeout=180)
        
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            return f"Screenshot captured successfully!\nVideo: {video_title}\nTimestamp: {timestamp}\nSaved to: {output_path}\nFile size: {file_size} bytes"
        
        return f"Screenshot failed. Method 1 return code: {download_result.returncode}\nMethod 2 return code: {screenshot_result.returncode}"

    except subprocess.TimeoutExpired:
        return "Error: Request timed out while capturing screenshot"
        
    except Exception as e:
        return f"Error capturing YouTube screenshot: {str(e)}"

@tool
def get_ytb_subtitle(url: str, language: Optional[str] = "en") -> str:
    """Get subtitles from a YouTube video in the specified language.
    
    Args:
        url: The URL of the YouTube video to get subtitles from.
        language (optional): The language of the subtitles to get. Default is "en". For example, "en" for English, "zh" for Chinese, "es" for Spanish, "fr" for French, "de" for German, "ja" for Japanese.
    """

    try:
        downloads_dir = "downloads"
        os.makedirs(downloads_dir, exist_ok=True)
        
        info_cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-playlist',
            url
        ]
        
        info_result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)
        
        if info_result.returncode != 0:
            return f"Error getting video info: {info_result.stderr}"
        
        try:
            video_info = json.loads(info_result.stdout)
        except json.JSONDecodeError:
            return "Error: Could not parse video information"
        
        video_id = video_info.get('id', 'unknown')
        video_title = video_info.get('title', 'Unknown Video')
        output_path = os.path.join(downloads_dir, video_id)
        
        subtitle_cmd = [
            'yt-dlp',
            '--write-sub',
            '--skip-download',
            '--sub-format', 'srt',
            '--sub-langs', language,
            '-o', output_path,
            url
        ]
        
        result = subprocess.run(subtitle_cmd, capture_output=True, text=True, timeout=60)
        
        # Check if subtitles were downloaded
        subtitle_files = glob.glob(f"{output_path}*.srt")
        
        if result.returncode == 0 and subtitle_files:
            subtitle_file = subtitle_files[0]
            file_size = os.path.getsize(subtitle_file)
            
            # Read and return the complete subtitle content
            try:
                with open(subtitle_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                return f"Subtitles downloaded successfully!\nVideo: {video_title}\nLanguage: {language}\nFile: {subtitle_file}\nFile size: {file_size} bytes\n\nComplete subtitles:\n{content}"
                
            except Exception as read_error:
                return f"Subtitles downloaded to: {subtitle_file}\nFile size: {file_size} bytes\nNote: Could not preview content: {str(read_error)}"
        
        # If specified language failed, try auto-generated subtitles
        if not subtitle_files:
            auto_cmd = [
                'yt-dlp',
                '--write-auto-sub',
                '--skip-download',
                '--sub-format', 'srt',
                '--sub-langs', language,
                '-o', output_path,
                url
            ]
            
            auto_result = subprocess.run(auto_cmd, capture_output=True, text=True, timeout=60)
            subtitle_files = glob.glob(f"{output_path}*.srt")
            
            if auto_result.returncode == 0 and subtitle_files:
                subtitle_file = subtitle_files[0]
                file_size = os.path.getsize(subtitle_file)
                return f"Auto-generated subtitles downloaded!\nVideo: {video_title}\nLanguage: {language}\nFile: {subtitle_file}\nFile size: {file_size} bytes\nNote: These are auto-generated subtitles"
        
        # If still no subtitles, try common languages
        if not subtitle_files:
            common_languages = ['en', 'zh-Hans', 'zh-Hant', 'es', 'fr', 'de', 'ja', 'ko']
            
            for lang in common_languages:
                if lang == language:
                    continue
                
                lang_cmd = [
                    'yt-dlp',
                    '--write-sub',
                    '--skip-download',
                    '--sub-format', 'srt',
                    '--sub-langs', lang,
                    '-o', output_path,
                    url
                ]
                
                lang_result = subprocess.run(lang_cmd, capture_output=True, text=True, timeout=30)
                subtitle_files = glob.glob(f"{output_path}*.srt")
                
                if lang_result.returncode == 0 and subtitle_files:
                    subtitle_file = subtitle_files[0]
                    file_size = os.path.getsize(subtitle_file)
                    return f"Subtitles found in different language!\nVideo: {video_title}\nRequested: {language}, Found: {lang}\nFile: {subtitle_file}\nFile size: {file_size} bytes"
        
        return f"No subtitles available for this video.\nVideo: {video_title}\nRequested language: {language}\nTried auto-generated and common languages, but none were found."
        
    except subprocess.TimeoutExpired:
        return "Error: Request timed out while downloading subtitles"

    except Exception as e:
        return f"Error getting YouTube subtitles: {str(e)}"

@tool
def get_ytb_audio(url: str) -> str:
    """Extract audio from a YouTube video and save as MP3.
    
    Args:
        url: The URL of the YouTube video to extract audio from.
    """

    try:
        video_id = None
        
        if 'youtube.com' in url:
            parsed_url = urlparse(url)
            video_id = parse_qs(parsed_url.query).get('v', [None])[0]
        elif 'youtu.be' in url:
            parsed_url = urlparse(url)
            video_id = parsed_url.path.lstrip('/')
        
        if not video_id:
            return f"Error: Could not extract video ID from URL: {url}"
        
        downloads_dir = "downloads"
        if not os.path.exists(downloads_dir):
            os.makedirs(downloads_dir)
        
        try:
            import yt_dlp
            
            output_template = os.path.join(downloads_dir, f"{video_id}_%(title)s.%(ext)s")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    # Extract info first
                    info = ydl.extract_info(url, download=False)
                    
                    result = f"YouTube Audio Extraction\n"
                    result += f"Video URL: {url}\n"
                    result += f"Video ID: {video_id}\n"
                    result += f"Title: {info.get('title', 'N/A')}\n"
                    result += f"Uploader: {info.get('uploader', 'N/A')}\n"
                    
                    # Duration
                    duration = info.get('duration')
                    if duration:
                        minutes, seconds = divmod(duration, 60)
                        hours, minutes = divmod(minutes, 60)
                        if hours:
                            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        else:
                            duration_str = f"{minutes:02d}:{seconds:02d}"
                        result += f"Duration: {duration_str}\n"
                    
                    result += "\n"
                    
                    # Check available audio formats
                    formats = info.get('formats', [])
                    audio_formats = [f for f in formats if f.get('acodec') != 'none']
                    
                    if audio_formats:
                        best_audio = max(audio_formats, key=lambda x: x.get('abr') or 0)
                        result += f"Best available audio quality: {best_audio.get('abr', 'Unknown')} kbps\n"
                        result += f"Audio codec: {best_audio.get('acodec', 'Unknown')}\n\n"
                    
                    # Download audio
                    result += "Starting audio download...\n"
                    try:
                        ydl.download([url])
                        result += "Audio download completed.\n"
                        
                        # Look for downloaded audio file
                        audio_files = []
                        for file in os.listdir(downloads_dir):
                            if video_id in file and file.endswith('.mp3'):
                                audio_files.append(os.path.join(downloads_dir, file))
                        
                        if audio_files:
                            for audio_file in audio_files:
                                file_size = os.path.getsize(audio_file)
                                file_size_mb = file_size / (1024 * 1024)
                                
                                result += f"\nDownloaded audio file: {audio_file}\n"
                                result += f"File size: {file_size_mb:.2f} MB\n"
                                
                                # Try to get audio metadata if possible
                                try:
                                    import mutagen
                                    from mutagen.mp3 import MP3
                                    
                                    audio = MP3(audio_file)
                                    result += f"Audio length: {audio.info.length:.2f} seconds\n"
                                    result += f"Bitrate: {audio.info.bitrate} bps\n"
                                    
                                except ImportError:
                                    result += "Install mutagen for detailed audio metadata: pip install mutagen\n"
                                except Exception:
                                    pass
                        else:
                            result += "Audio file not found after download. Check downloads directory.\n"
                    
                    except Exception as e:
                        result += f"Error downloading audio: {str(e)}\n"
                    
                    return result
                    
                except Exception as e:
                    return f"Error extracting video info: {str(e)}"
                    
        except ImportError:
            return (
                f"Audio extraction not available.\n"
                f"Video URL: {url}\n\n"
                f"To extract audio, install required packages:\n"
                f"pip install yt-dlp\n"
                f"Note: This also requires ffmpeg to be installed on your system.\n"
                f"For audio metadata: pip install mutagen\n"
            )
        
    except Exception as e:
        return f"Error getting YouTube audio: {str(e)}"


if __name__ == "__main__":
    # url = "https://www.youtube.com/watch?v=5qzM8G5M00s"
    url="https://www.youtube.com/watch?v=2Njmx-UuU3M"
    # 截图示例
    # get_ytb_screenshot(url, "00:01:00")
    # 获取字幕
    get_ytb_subtitle(url)
    # 获取音频
    # get_ytb_audio(url)
