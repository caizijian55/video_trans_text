import streamlit as st
import requests
import os
import re
import pandas as pd
from openai import OpenAI
import tempfile
import subprocess
from io import BytesIO
import time
import random

# --- 核心配置区（直接写死在代码里，按你的需求保留） ---
SILICONFLOW_API_KEY = "sk-pyoeczevtyvjxolwtiwslujkncsmwdihvbrowwbatzjzekge"
PARSING_API_URL = "https://api.bugpk.com/api/douyin"

st.set_page_config(page_title="批量视频转文字工具", layout="wide")

SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
ASR_MODEL = "iic/SenseVoiceSmall"

# UA 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

def get_random_header():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://www.douyin.com/"
    }

def extract_url(text):
    if not text:
        return None
    pattern = r'(https?://[^\s]+)'
    match = re.search(pattern, text)
    return match.group(1) if match else None

def download_video_via_api(douyin_url, parser_api_url, status_callback=None):
    MAX_RETRIES_PARSE = 3
    MAX_RETRIES_DOWNLOAD = 3
    video_url = None
    parse_error = None
    
    if '?' in parser_api_url:
        api_full_url = f"{parser_api_url}&url={douyin_url}"
    else:
        api_full_url = f"{parser_api_url}?url={douyin_url}"
        
    for i in range(MAX_RETRIES_PARSE):
        try:
            headers_parse = get_random_header()
            response = requests.get(api_full_url, headers=headers_parse, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, dict):
                if "data" in data and isinstance(data["data"], dict):
                    video_url = data["data"].get("url") or data["data"].get("play_addr")
                elif "url" in data:
                    video_url = data["url"]
                elif "video_url" in data:
                    video_url = data["video_url"]
            
            if video_url:
                break
            else:
                parse_error = f"未找到视频 URL. 返回: {str(data)[:200]}"
                time.sleep(2)
                
        except Exception as e:
            parse_error = str(e)
            time.sleep(2)
            
    if not video_url:
        return None, f"解析失败: {parse_error}"

    temp_dir = tempfile.mkdtemp()
    mp4_path = os.path.join(temp_dir, "video.mp4")
    download_success = False
    download_error = None
    
    for i in range(MAX_RETRIES_DOWNLOAD):
        try:
            headers_download = get_random_header()
            video_resp = requests.get(video_url, headers=headers_download, stream=True, timeout=30)
            video_resp.raise_for_status()
            
            with open(mp4_path, "wb") as f:
                for chunk in video_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            download_success = True
            break
        except Exception as e:
            download_error = str(e)
            time.sleep(3)
            
    if not download_success:
        return None, f"下载失败: {download_error}"

    try:
        mp3_path = os.path.join(temp_dir, "audio.mp3")
        command = [
            "ffmpeg", "-y",
            "-i", mp4_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "4",
            mp3_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.remove(mp4_path)
        return mp3_path, "ok"
    except Exception as e:
        if os.path.exists(mp4_path):
            os.remove(mp4_path)
        return None, f"转码失败: {str(e)}"

def transcribe_audio(client, file_path):
    try:
        with open(file_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model=ASR_MODEL,
                file=audio_file
            )
        return transcription.text
    except Exception as e:
        return f"转录失败: {str(e)}"

# --- UI 侧边栏 ---
uploaded_file = st.sidebar.file_uploader("Excel/CSV 批量上传", type=["xlsx", "xls", "csv"])
input_text = st.sidebar.text_area("或输入链接 (一行一个)", height=100)

# --- UI 主界面 ---
st.title("批量视频转文字工具")

if st.button("开始处理", type="primary"):
    valid_urls = []
    if input_text.strip():
        lines = input_text.strip().split("\n")
        for line in lines:
            url = extract_url(line)
            if url:
                valid_urls.append(url)
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith(".csv"):
                df_upload = pd.read_csv(uploaded_file)
            else:
                df_upload = pd.read_excel(uploaded_file)
            for _, row in df_upload.iterrows():
                row_str = " ".join(row.astype(str).values)
                url = extract_url(row_str)
                if url:
                    valid_urls.append(url)
        except Exception as e:
            st.error(f"读取文件失败: {e}")
    valid_urls = list(set(valid_urls))
    
    if not valid_urls:
        st.warning("请先输入视频链接或上传文件")
    else:
        client = OpenAI(api_key=SILICONFLOW_API_KEY, base_url=SILICONFLOW_BASE_URL)
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        total = len(valid_urls)
        
        for i, url in enumerate(valid_urls):
            status_text.text(f"正在处理: {url} ({i+1}/{total})")
            
            def update_status(msg):
                status_text.markdown(msg)
                
            audio_path, err = download_video_via_api(url, PARSING_API_URL, status_callback=update_status)
            
            if audio_path and os.path.exists(audio_path):
                transcript = transcribe_audio(client, audio_path)
                results.append({
                    "原始链接": url,
                    "状态": "成功" if not transcript.startswith("转录失败") else "失败",
                    "视频逐字稿": transcript
                })
                try:
                    os.remove(audio_path)
                    os.rmdir(os.path.dirname(audio_path))
                except:
                    pass
            else:
                results.append({"原始链接": url, "状态": "失败", "视频逐字稿": ""})
            
            progress_bar.progress((i + 1) / total)
            if i < total - 1:
                time.sleep(random.uniform(1.5, 3))

        status_text.text("✅ 处理完成")
        df = pd.DataFrame(results)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        st.download_button("导出 Excel", buffer.getvalue(), "transcripts.xlsx")
        st.dataframe(df, hide_index=True)