import json
import os
import re

import requests
import streamlit as st
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")


SYSTEM_PROMPT = """
Bạn là trợ lý gợi ý phim thông minh.
Không tự bịa tên phim. Không trả danh sách phim.
Nhiệm vụ của bạn là hiểu yêu cầu người dùng và chuyển thành bộ lọc tìm phim trên TMDB.

Chỉ trả về JSON theo đúng format sau, KHÔNG thêm bất kỳ text nào khác ngoài JSON:

{
    "criteria": {
        "genres": ["Tên genre tiếng Anh, ví dụ: Action, Comedy, Drama"],
        "release_year_from": 1990,
        "release_year_to": 2026,
        "vote_average_gte": 6.0,
        "sort_by": "popularity.desc"
    },
    "reason": "Một câu tiếng Việt giải thích vì sao bộ lọc này phù hợp",
    "message": null
}

Quy tắc:
- genres chỉ dùng tên genre phim phổ biến của TMDB bằng tiếng Anh.
- Nếu user không nói rõ thể loại, chọn 1-3 genres hợp lý từ ngữ cảnh.
- release_year_from, release_year_to có thể là null nếu user không yêu cầu thời gian.
- vote_average_gte mặc định 6.0 nếu user không yêu cầu phim dở hoặc thử nghiệm.
- sort_by chỉ dùng một trong: popularity.desc, vote_average.desc, revenue.desc, primary_release_date.desc.
- Nếu câu hỏi quá mơ hồ, trả criteria rỗng hợp lý và dùng message để hỏi thêm.
- Output hiển thị cho người dùng là tiếng Việt.
"""


REVIEW_PROMPT = """
Bạn là trợ lý review phim bằng tiếng Việt.
Bạn sẽ nhận danh sách phim thật từ TMDB, gồm tmdb_id, title, release_date, vote_average và overview tiếng Anh.

Hãy viết nhận xét riêng cho từng phim dựa trên nội dung phim, điểm TMDB và yêu cầu người dùng.
Không dịch máy từng chữ overview. Không dùng cùng một câu cho nhiều phim.
Không bịa thông tin ngoài dữ liệu được cung cấp.

Chỉ trả về JSON theo đúng format sau, KHÔNG thêm bất kỳ text nào khác ngoài JSON:

{
    "reviews": [
        {
            "tmdb_id": 123,
            "review": "Một đoạn tiếng Việt 1-2 câu giải thích nội dung/chất phim và vì sao phù hợp."
        }
    ]
}
"""


SUMMARY_INTENT_PROMPT = """
Bạn là agent phân loại yêu cầu chatbot phim.
Nhiệm vụ: xác định user có đang yêu cầu tóm tắt nội dung chi tiết của một phim cụ thể không.

Chỉ trả về JSON theo đúng format sau, KHÔNG thêm text ngoài JSON:

{
    "is_summary_request": true,
    "title": "Tên phim user nhắc tới, giữ nguyên gần nhất có thể",
    "message": null
}

Quy tắc:
- is_summary_request là true nếu user hỏi tóm tắt, kể nội dung, giải thích cốt truyện, review chi tiết nội dung của một phim cụ thể.
- title phải lấy từ chính câu user, không tự bịa tên phim.
- Nếu user không nhắc tên phim cụ thể, is_summary_request là true nhưng title là null và message hỏi user muốn tóm tắt phim nào.
- Nếu user chỉ muốn gợi ý phim, is_summary_request là false.
"""


SUMMARY_PROMPT = """
Bạn là agent tóm tắt nội dung phim bằng tiếng Việt.
Bạn sẽ nhận dữ liệu phim thật từ TMDB gồm title, release_date, vote_average, genres và overview tiếng Anh.

Hãy viết một đoạn văn tiếng Việt tóm tắt chi tiết nội dung phim theo nhu cầu user.
Yêu cầu bắt buộc:
- Viết ít nhất 5 câu.
- Không dùng bullet list.
- Không dùng tiếng Anh trừ tên riêng hoặc tên phim.
- Không bịa chi tiết ngoài dữ liệu được cung cấp.
- Nếu overview quá ngắn, hãy nói rõ phần tóm tắt dựa trên dữ liệu TMDB hiện có, rồi phân tích tiền đề, xung đột, không khí phim và kiểu khán giả phù hợp.

Chỉ trả về JSON theo đúng format sau, KHÔNG thêm text ngoài JSON:

{
    "summary": "Đoạn văn tiếng Việt ít nhất 5 câu."
}
"""


TMDB_GENRES = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "history": 36,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "science fiction": 878,
    "sci-fi": 878,
    "tv movie": 10770,
    "thriller": 53,
    "war": 10752,
    "western": 37,
}

SORT_BY_ALLOWLIST = {
    "popularity.desc",
    "vote_average.desc",
    "revenue.desc",
    "primary_release_date.desc",
}


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self):
        self.api_key = TMDB_API_KEY

    def search_movie(self, title: str) -> dict | None:
        if not self.api_key or not title:
            return None

        try:
            response = requests.get(
                f"{self.BASE_URL}/search/movie",
                params={
                    "api_key": self.api_key,
                    "query": title,
                    "language": "en-US",
                    "include_adult": "false",
                    "page": 1,
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None

        results = response.json().get("results", [])
        if not results:
            return None

        title_lower = title.strip().lower()
        for movie in results:
            if (movie.get("title") or "").strip().lower() == title_lower:
                return movie

        return results[0]

    def movie_details(self, tmdb_id: int) -> dict | None:
        if not self.api_key or not tmdb_id:
            return None

        try:
            response = requests.get(
                f"{self.BASE_URL}/movie/{tmdb_id}",
                params={
                    "api_key": self.api_key,
                    "language": "en-US",
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None

        return response.json()

    def discover_movies(self, criteria: dict, limit: int = 8) -> list[dict]:
        if not self.api_key:
            return []

        criteria = criteria or {}
        genres = criteria.get("genres") or []
        genre_ids = self._genre_ids(genres)
        sort_by = criteria.get("sort_by") or "popularity.desc"
        if sort_by not in SORT_BY_ALLOWLIST:
            sort_by = "popularity.desc"

        params = {
            "api_key": self.api_key,
            "language": "en-US",
            "include_adult": "false",
            "include_video": "false",
            "page": 1,
            "sort_by": sort_by,
            "vote_count.gte": 100,
        }

        if genre_ids:
            params["with_genres"] = "|".join(str(genre_id) for genre_id in genre_ids)

        vote_average = criteria.get("vote_average_gte")
        if isinstance(vote_average, (int, float)):
            params["vote_average.gte"] = max(0, min(float(vote_average), 10))

        year_from = criteria.get("release_year_from")
        if isinstance(year_from, int):
            params["primary_release_date.gte"] = f"{year_from}-01-01"

        year_to = criteria.get("release_year_to")
        if isinstance(year_to, int):
            params["primary_release_date.lte"] = f"{year_to}-12-31"

        try:
            response = requests.get(
                f"{self.BASE_URL}/discover/movie",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            return []

        return (response.json().get("results") or [])[:limit]

    @staticmethod
    def _genre_ids(genres: list) -> list[int]:
        genre_ids = []

        for genre in genres:
            key = str(genre).strip().lower()
            genre_id = TMDB_GENRES.get(key)
            if genre_id and genre_id not in genre_ids:
                genre_ids.append(genre_id)

        return genre_ids


class FilmRecommendationChatbot:
    def __init__(self, client: Groq, tmdb_client: TMDBClient):
        self.client = client
        self.tmdb_client = tmdb_client

    def get_recommendations(self, messages: list) -> str:
        groq_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in messages
        ]

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                *groq_messages,
            ],
            temperature=0,
        )

        return response.choices[0].message.content

    @staticmethod
    def parse_response(raw_response: str) -> dict:
        cleaned = re.sub(r"```json|```", "", raw_response).strip()
        return json.loads(cleaned)

    def detect_summary_request(self, prompt: str) -> dict:
        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": SUMMARY_INTENT_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0,
        )

        try:
            return self.parse_response(response.choices[0].message.content)
        except Exception:
            return {"is_summary_request": False, "title": None, "message": None}

    def summarize_movie(self, user_prompt: str, title: str) -> str:
        movie = self.tmdb_client.search_movie(title)
        if not movie:
            return f"Không tìm thấy phim `{title}` trên TMDB. Bạn kiểm tra lại tên phim giúp tôi nhé."

        details = self.tmdb_client.movie_details(movie.get("id")) or movie
        movie_payload = {
            "tmdb_id": details.get("id") or movie.get("id"),
            "title": details.get("title") or movie.get("title"),
            "release_date": details.get("release_date") or movie.get("release_date"),
            "vote_average": details.get("vote_average") or movie.get("vote_average"),
            "genres": [
                genre.get("name")
                for genre in details.get("genres", [])
                if genre.get("name")
            ],
            "overview": details.get("overview") or movie.get("overview"),
        }

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": SUMMARY_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_request": user_prompt,
                            "movie": movie_payload,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.2,
        )

        try:
            data = self.parse_response(response.choices[0].message.content)
            summary = data.get("summary")
            if summary:
                return summary
        except Exception:
            pass

        return (
            f"{movie_payload['title']} là phim có nội dung xoay quanh: "
            f"{movie_payload.get('overview') or 'TMDB hiện chưa có mô tả chi tiết.'}"
        )

    def movies_from_criteria(self, data: dict) -> list[dict]:
        criteria = data.get("criteria") or {}
        has_criteria = any(
            criteria.get(key)
            for key in (
                "genres",
                "release_year_from",
                "release_year_to",
                "vote_average_gte",
                "sort_by",
            )
        )

        if data.get("message") and not has_criteria:
            return []

        return self.tmdb_client.discover_movies(criteria)

    def get_movie_reviews(self, user_prompt: str, movies: list) -> dict[int, str]:
        movie_payload = []

        for movie in movies:
            movie_payload.append(
                {
                    "tmdb_id": movie.get("id"),
                    "title": movie.get("title"),
                    "release_date": movie.get("release_date"),
                    "vote_average": movie.get("vote_average"),
                    "overview": movie.get("overview"),
                }
            )

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": REVIEW_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_request": user_prompt,
                            "movies": movie_payload,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.3,
        )

        try:
            data = self.parse_response(response.choices[0].message.content)
        except Exception:
            return {}

        reviews = {}
        for item in data.get("reviews", []):
            tmdb_id = item.get("tmdb_id")
            review = item.get("review")
            if isinstance(tmdb_id, int) and review:
                reviews[tmdb_id] = review

        return reviews

    @staticmethod
    def _table_cell(value) -> str:
        text = str(value or "-").replace("\n", " ").replace("|", "\\|").strip()
        return text or "-"

    @classmethod
    def build_movie_table(cls, movies: list, reviews: dict[int, str] | None = None) -> str:
        rows = []
        reviews = reviews or {}

        for movie in movies:
            tmdb_id = movie.get("id")
            title = (movie.get("title") or "Không rõ").strip()
            release_date = movie.get("release_date") or "-"
            rating = movie.get("vote_average")

            link = f"[{title}](?view=details&id={tmdb_id})" if tmdb_id else title
            rating_text = (
                f"{float(rating):.1f}/10"
                if isinstance(rating, (int, float))
                else "-"
            )
            review = reviews.get(tmdb_id) or (
                f"{title} là lựa chọn phù hợp với bộ lọc hiện tại, "
                f"có điểm TMDB {rating_text} và phát hành ngày {release_date}."
            )

            rows.append(
                "| "
                f"{cls._table_cell(link)} | "
                f"{cls._table_cell(release_date)} | "
                f"{cls._table_cell(rating_text)} | "
                f"{cls._table_cell(review)} |"
            )

        table = (
            "| Phim | Ngày phát hành | Điểm TMDB | Nội dung và đánh giá |\n"
            "|------|----------------|-----------|----------------------|\n"
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
        self.tmdb_client = TMDBClient()
        self.chatbot = FilmRecommendationChatbot(self.client, self.tmdb_client)

    def initialize_session(self):
        if "messages" not in st.session_state:
            st.session_state.messages = []

    def render_history(self):
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg.get("display_content") or msg["content"])

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
            with st.spinner("Đang suy nghĩ ...."):
                summary_response = self.render_summary_response(prompt)
                if summary_response:
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": summary_response,
                            "display_content": summary_response,
                        }
                    )
                    return

                raw_response, data = self.chatbot.process(
                    st.session_state.messages
                )

                if data:
                    rendered_response = self.render_json_response(data)
                else:
                    rendered_response = raw_response
                    st.markdown(raw_response)

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": raw_response,
                        "display_content": rendered_response,
                    }
                )

    def render_json_response(self, data: dict):
        rendered_parts = []

        if data.get("message"):
            st.markdown(data["message"])
            rendered_parts.append(data["message"])

        movies = self.chatbot.movies_from_criteria(data)

        if movies:
            user_prompt = self.latest_user_prompt()
            reviews = self.chatbot.get_movie_reviews(user_prompt, movies)
            table = self.chatbot.build_movie_table(movies, reviews)
            st.markdown(table)
            rendered_parts.append(table)
        elif not data.get("message"):
            fallback = "Không tìm thấy phim phù hợp trên TMDB. Bạn thử mô tả rõ hơn nhé."
            st.markdown(fallback)
            rendered_parts.append(fallback)

        return "\n\n".join(rendered_parts) if rendered_parts else ""

    def render_summary_response(self, prompt: str) -> str | None:
        intent = self.chatbot.detect_summary_request(prompt)

        if not intent.get("is_summary_request"):
            return None

        title = intent.get("title")
        if not title:
            message = intent.get("message") or "Bạn muốn tôi tóm tắt chi tiết phim nào?"
            st.markdown(message)
            return message

        summary = self.chatbot.summarize_movie(prompt, title)
        st.markdown(summary)
        return summary

    @staticmethod
    def latest_user_prompt() -> str:
        for msg in reversed(st.session_state.messages):
            if msg.get("role") == "user":
                return msg.get("content", "")

        return ""

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
