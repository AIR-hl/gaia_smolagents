from smolagents import tool
import subprocess
import json
import os

class YouTubeTool:
    def get_video_info(self, video_url):
        """
        获取视频的详细信息，包括时长、格式等
        """
        try:
            cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-playlist',
                video_url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"获取视频信息失败: {result.stderr}")
            video_info = json.loads(result.stdout)
            return video_info
        except Exception as e:
            print(f"获取视频信息出错: {e}")
            return None

    def select_video_format(self, video_info):
        """
        智能选择最适合截图的视频格式
        """
        formats = video_info.get('formats', [])
        video_only_formats = [
            f for f in formats
            if f.get('vcodec', 'none') != 'none' and f.get('acodec', 'none') == 'none'
        ]
        if not video_only_formats:
            video_only_formats = [
                f for f in formats if f.get('vcodec', 'none') != 'none'
            ]
        suitable_formats = [f for f in video_only_formats if f.get('height', 0) <= 1024]
        if suitable_formats:
            selected_format = max(suitable_formats, key=lambda x: x.get('height', 0))
        else:
            selected_format = video_only_formats[0] if video_only_formats else formats[0]
        return selected_format

    def screenshot(self, url, timestamp, output_path="streaming_screenshot.jpg"):
        """
        对指定YouTube视频在指定时间点截图
        """
        try:
            video_info = self.get_video_info(url)
            if not video_info:
                print("无法获取视频信息，截图失败")
                return None
            selected_format = self.select_video_format(video_info)
            stream_url = selected_format['url']
            cmd = [
                'ffmpeg',
                '-loglevel', 'error',
                '-ss', str(timestamp),
                '-i', stream_url,
                '-vframes', '1',
                '-avoid_negative_ts', 'make_zero',
                '-q:v', '2',
                '-y', output_path
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 and os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                if file_size > 1000:
                    print(f"截图成功: {output_path}")
                    return output_path
                else:
                    print("截图文件创建失败")
                    return None
            else:
                print(f"FFmpeg执行失败: {result.stderr.strip()}")
                return None
        except Exception as e:
            print(f"Screenshot Error: {e}")
            return None

    def get_subtitles(self, url, out_path="subtitles.srt", lang="en"):
        """
        获取YouTube视频的字幕，默认下载英文字幕
        """
        try:
            cmd = [
                'yt-dlp',
                '--write-auto-sub',
                '--sub-format', 'srt',
                '--skip-download',
                '--sub-lang', lang,
                '-o', out_path,
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            # yt-dlp 会将字幕保存为 {out_path}.{lang}.srt
            base = out_path
            srt_file = None
            for suffix in [f".{lang}.srt", ".en.srt", ".zh-Hans.srt", ".srt"]:
                candidate = base + suffix
                if os.path.exists(candidate):
                    srt_file = candidate
                    break
            if srt_file:
                print(f"字幕文件下载成功: {srt_file}")
                return srt_file
            else:
                print(f"字幕文件未找到, yt-dlp输出: {result.stderr.strip()}")
                return None
        except Exception as e:
            print(f"获取字幕出错: {e}")
            return None

    def get_audio(self, url, out_path="audio.m4a"):
        """
        下载YouTube视频的音频部分
        """
        try:
            cmd = [
                'yt-dlp',
                '-f', 'bestaudio',
                '-x',
                '--audio-format', 'm4a',
                '-o', out_path,
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if os.path.exists(out_path):
                print(f"音频文件下载成功: {out_path}")
                return out_path
            else:
                print(f"音频文件未找到, yt-dlp输出: {result.stderr.strip()}")
                return None
        except Exception as e:
            print(f"音频获取出错: {e}")
            return None

if __name__=="__main__":
    url = "https://www.youtube.com/watch?v=5qzM8G5M00s"
    tool = YouTubeTool()
    # 截图示例
    tool.screenshot(url, "00:01:15", "screenshot.jpg")
    # 获取英文字幕
    tool.get_subtitles(url, "subtitles", lang="en")
    # 获取音频
    tool.get_audio(url, "audio.m4a")
