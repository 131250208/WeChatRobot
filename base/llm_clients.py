#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import re
from datetime import datetime

import httpx
import logging
import requests
import google.generativeai as genai
import ollama

from openai import OpenAI, APIConnectionError, APIError, AuthenticationError
from base.chatglm.code_kernel import CodeKernel, execute
from base.chatglm.tool_registry import dispatch_tool, extract_code, get_tools
from wcferry import Wcf
from sparkdesk_web.core import SparkWeb
from zhipuai import ZhipuAI


# 获取工具方法
functions = get_tools()


class LLMClient:
    def __init__(self, *args, **kwargs) -> None:
        self.LOG = logging.getLogger(self.__class__.__name__)
    
    @staticmethod
    def value_check(conf: dict) -> bool:
        raise NotImplementedError("Subclasses must implement value_check.")
    
    def get_answer(self, chat_hist_messages: list) -> str:
        raise NotImplementedError("Subclasses must implement get_answer.")

class ChatGPT(LLMClient):
    def __init__(self, conf: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        key = conf.get("key")
        api = conf.get("api")
        proxy = conf.get("proxy")
        prompt = conf.get("prompt")
        self.model = conf.get("model", "gpt-3.5-turbo")
        if proxy:
            self.client = OpenAI(api_key=key, base_url=api, http_client=httpx.Client(proxy=proxy))
        else:
            self.client = OpenAI(api_key=key, base_url=api)
        self.system_content_msg = {"role": "system", "content": prompt}

    def __repr__(self):
        return "ChatGPT"

    @staticmethod
    def value_check(conf: dict) -> bool:
        return conf and conf.get("key") and conf.get("api") and conf.get("prompt")

    def get_answer(self, chat_hist_messages: list) -> str:
        rsp = ""
        try:
            ret = self.client.chat.completions.create(
                model=self.model,
                messages=chat_hist_messages,
                temperature=0.7
            )
            rsp = ret.choices[0].message.content
            rsp = rsp[2:] if rsp.startswith("\n\n") else rsp
            rsp = rsp.replace("\n\n", "\n")
        except AuthenticationError:
            self.LOG.error("OpenAI API 认证失败，请检查 API 密钥是否正确")
        except APIConnectionError:
            self.LOG.error("无法连接到 OpenAI API，请检查网络连接")
        except APIError as e1:
            self.LOG.error(f"OpenAI API 返回了错误：{str(e1)}")
        except Exception as e0:
            self.LOG.error(f"发生未知错误：{str(e0)}")
    
        return rsp
    
class ChatGLM(LLMClient):
    def __init__(self, config={}, wcf: Wcf = None, max_retry=5, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        key = config.get("key", "empty")
        api = config.get("api")
        proxy = config.get("proxy")
        if proxy:
            self.client = OpenAI(api_key=key, base_url=api, http_client=httpx.Client(proxy=proxy))
        else:
            self.client = OpenAI(api_key=key, base_url=api)
        self.chat_type = {}
        self.max_retry = max_retry
        self.wcf = wcf
        self.filePath = config["file_path"]
        self.kernel = CodeKernel()
        self.system_content_msg = {"role": "system", "content": config["prompt"]}

    def __repr__(self):
        return "ChatGLM"

    @staticmethod
    def value_check(conf: dict) -> bool:
        return super().value_check(conf)

    def get_answer(self, chat_hist_messages: list) -> str:
        return super().get_answer(chat_hist_messages)


class BardAssistant(LLMClient):
    def __init__(self, conf: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._api_key = conf["api_key"]
        self._model_name = conf["model_name"]
        self._prompt = conf["prompt"]
        self._proxy = conf["proxy"]

        genai.configure(api_key=self._api_key)
        self._bard = genai.GenerativeModel(self._model_name)

    def __repr__(self):
        return "BardAssistant"

    @staticmethod
    def value_check(conf: dict) -> bool:
        return super().value_check(conf)

    def get_answer(self, chat_hist_messages: list) -> str:
        return super().get_answer(chat_hist_messages)


class Ollama(LLMClient):
    def __init__(self, conf: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.prompt = conf.get("prompt")
        self.model = conf.get("model")

    def __repr__(self):
        return "Ollama"

    @staticmethod
    def value_check(conf: dict) -> bool:
        return super().value_check(conf)

    def get_answer(self, chat_hist_messages: list) -> str:
        return super().get_answer(chat_hist_messages)


class TigerBot(LLMClient):
    def __init__(self, tbconf=None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tburl = "https://api.tigerbot.com/bot-service/ai_service/gpt"
        self.tbheaders = {"Authorization": "Bearer " + tbconf["key"]}
        self.tbmodel = tbconf["model"]
        self.fallback = ["滚", "快滚", "赶紧滚"]

    def __repr__(self):
        return "TigerBot"

    @staticmethod
    def value_check(conf: dict) -> bool:
        return super().value_check(conf)

    def get_answer(self, chat_hist_messages: list) -> str:
        return super().get_answer(chat_hist_messages)


class XinghuoWeb(LLMClient):
    def __init__(self, xhconf=None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sparkWeb = SparkWeb(
            cookie=xhconf["cookie"],
            fd=xhconf["fd"],
            GtToken=xhconf["GtToken"],
        )
        self._chat = self._sparkWeb.create_continuous_chat()
        if xhconf.get("prompt"):
            self._chat.chat(xhconf["prompt"])

    def __repr__(self):
        return "XinghuoWeb"

    @staticmethod
    def value_check(conf: dict) -> bool:
        return super().value_check(conf)

    def get_answer(self, chat_hist_messages: list) -> str:
        return super().get_answer(chat_hist_messages)


class ZhiPu(LLMClient):
    def __init__(self, conf: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = conf.get("api_key")
        self.model = conf.get("model", "glm-4")
        self.client = ZhipuAI(api_key=self.api_key)

    def __repr__(self):
        return "ZhiPu"

    @staticmethod
    def value_check(conf: dict) -> bool:
        return super().value_check(conf)

    def get_answer(self, chat_hist_messages: list) -> str:
        return super().get_answer(chat_hist_messages)


if __name__ == "__main__":
    pass
