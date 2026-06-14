import json
import re
import os
import requests
from typing_extensions import overload

import streamlit as st
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")


SYSTEM_PROMPT = """
Bạn là trợ lý gợi ý phim thông minh.
Khi user hỏi về phim hãy trả về JSON theo đúng format sau, KHÔNG thêm bất kỳ text nào khác ngoài JSON, số lượng phim trả ra output cho người dùng >= 5:

{
    "movies": [
        {
            "title": "Tên phim tiếng Anh",
            "title_vi": "Tên phim tiếng Việt",
            "year": "Năm phát hành",
            "reason": "Lý do phù hợp ngắn gọn"
        }
    ],
    "message": "Lời nhắn thêm nếu cần hỏi thêm thông tin, hoặc null"
}

Nếu câu hỏi mơ hồ vẫn trả về JSON nhưng để movies rỗng và dùng message để hỏi thêm.
"""
# st.set_page_config(
#     page_title="Movie Chatbot",
#     page_icon="🤖",
# )

class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self):
        self.api_key = TMDB_API_KEY

    def get_overview(self, title: str) -> str:
        response = requests.get(
            f"{self.BASE_URL}/search/movie",
            params={
                "api_key": self.api_key,
                "query": title,
                "language": "en-US",
            },
            timeout=10,
        )

        response.raise_for_status()

        results = response.json().get("results", [])

        if not results:
            return ""

        # exact title match first
        title_lower = title.lower()

        for movie in results:
            if movie.get("title", "").lower() == title_lower:
                return movie.get("overview", "")

        # fallback to first result
        return results[0].get("overview", "")

class FilmRecommendationChatbot:
    def __init__(self, client: Groq):
        self.client = client

    def get_recommendations(self, messages: list) -> str:
        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",   
                    "content": SYSTEM_PROMPT,
                },
                *messages,
            ],
        )

        return response.choices[0].message.content

    @staticmethod
    def parse_response(raw_response: str) -> dict:
        cleaned = re.sub(r"```json|```", "", raw_response).strip()
        return json.loads(cleaned)

    @staticmethod
    def build_movie_table(movies: list) -> str:
        rows = []

        for movie in movies:
            title = movie.get("title", "")
            title_vi = movie.get("title_vi", "")
            year = movie.get("year", "")
            reason = movie.get("reason", "")


          
            search_url = (
                f"https://www.google.com/search?q={title}"
            )
            
            link = f"[{title_vi} /{title}]({search_url})"

            rows.append(
                f"| {link} | {year} | {reason} |"
            )

        table = (
            "| Phim | Năm phát hành | Lý do phù hợp |\n"
            "|------|--------------|---------------|\n"
        )

        table += "\n".join(rows)

        return table

    def process(self, messages: list) -> tuple[str, dict | None]:
        raw_response = self.get_recommendations(messages)

        try:
            data = self.parse_response(raw_response)
            return raw_response, data
        except Exception:
            return raw_response, None


class MovieChatApp:
    def __init__(self):
        self.client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        self.chatbot = FilmRecommendationChatbot(self.client)

    def initialize_session(self):
        if "messages" not in st.session_state:
            st.session_state.messages = []

    def render_history(self):
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    def handle_user_input(self):
        prompt = st.chat_input("Bạn muốn xem phim gì hôm nay?")

        if not prompt:
            return

        st.session_state.messages.append(
            {"role": "user", "content": prompt}
        )

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Đang tìm phim..."):
                raw_response, data = self.chatbot.process(
                    st.session_state.messages
                )

                if data:
                    self.render_json_response(data)
                else:
                    st.markdown(raw_response)

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": raw_response,
                    }
                )

    def render_json_response(self, data: dict):
        if data.get("message"):
            st.markdown(data["message"])

        movies = data.get("movies", [])

        if movies:
            table = self.chatbot.build_movie_table(movies)
            st.markdown(table)

    def render_clear_button(self):
        if st.button("🗑️ Xóa lịch sử"):
            st.session_state.messages = []
            st.rerun()

    def run(self):


        st.title("🤖 Movie Chatbot")
        st.caption("Bạn đang muốn xem phim gì? Cho tôi biết bạn đang tìm kiếm điều gì nhé!")

        self.initialize_session()
        self.render_history()
        self.handle_user_input()
        self.render_clear_button()
