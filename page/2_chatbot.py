import streamlit as st
from groq import Groq

# Setup
st.set_page_config(page_title="Movie Chatbot", page_icon="🤖")
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

st.title("🤖 Movie Chatbot")
st.caption("Hỏi tôi bất cứ điều gì về phim!")

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Hiện lịch sử chat
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Nhận input
if prompt := st.chat_input("Bạn muốn xem phim gì hôm nay?"):
    
    # Hiện tin nhắn user
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Gọi Groq
    with st.chat_message("assistant"):
        with st.spinner("Đang tìm phim..."):
            res = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {
                        "role": "system",
                        "content": """Bạn là trợ lý gợi ý phim thông minh.
                        Khi user hỏi về phim hãy:
                        1. Gợi ý 3-5 phim phù hợp
                        2. Giải thích ngắn tại sao mỗi phim phù hợp
                        3. Nếu câu hỏi mơ hồ → hỏi thêm thể loại hoặc sở thích
                        Trả lời bằng tiếng Việt, thân thiện."""
                    },
                    *st.session_state.messages
                ]
            )
            reply = res.choices[0].message.content
            st.markdown(reply)

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply
    })

# Nút xóa chat
if st.button("🗑️ Xóa lịch sử"):
    st.session_state.messages = []
    st.rerun()