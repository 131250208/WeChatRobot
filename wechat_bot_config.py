from config import *
from prompts.prompts4characters import *
from prompts.prompts4imgteller import *

CHARACTER_NAMES = LIU_JI_SHOU_NAMES
CHARACTER_SYSTEM_PROMPT = LIU_JI_SHOU_PROMPT + "\n" + IMG_TELL_SYSTEM_PROMPT

# 聊天模型
CHAT_CLIENT = "DeepSeek"
CHAT_MODEL_NAME = "Pro/deepseek-ai/DeepSeek-V3"
CHAT_MODEL_API_KEY = SILICONFLOW_API_KEY
CHAT_MODEL_BASE_URL = SILICONFLOW_BASE_URL

# 推理模型
REASON_CLIENT = "DeepSeek"
REASON_MODEL_NAME = "deepseek-ai/DeepSeek-R1"
REASON_MODEL_API_KEY = SILICONFLOW_API_KEY
REASON_MODEL_BASE_URL = SILICONFLOW_BASE_URL

# 允许响应的群聊ID列表
ENABLED_GROUPS = ["52343524969@chatroom"] # "45978299611@chatroom"

# 消息接收者配置
NEWS_RECEIVERS = ["filehelper"]
REPORT_REMINDER_RECEIVERS = ["filehelper"]

# 消息发送速率限制（每分钟最大发送消息数）
SEND_RATE_LIMIT = 6

# 自动发送消息间隔（分钟）
AUTO_SEND_INTERVAL = 3

# 天气相关配置
WEATHER_CONFIG = {
    "city_code": "101010100",  # 北京城市代码
    "receivers": ["filehelper"]
}

