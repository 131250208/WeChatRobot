# -*- coding: utf-8 -*-
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents.ImgStoryTeller import ImgStoryTeller

import logging
import re
import time
import xml.etree.ElementTree as ET
from queue import Empty
from threading import Thread

from wcferry import Wcf, WxMsg

from base.func_chengyu import cy
from base.func_weather import Weather
from base.func_news import News

from job_mgmt import Job
import llm_clients
from datetime import datetime
from utils import LoggerConfig, parse_xml_msg, mentions
import wechat_bot_config as config

__version__ = "39.2.4.0"


class Robot(Job):
    """个性化自己的机器人
    """

    def __init__(self, wcf: Wcf, 
                 chat_client_name: str = "ChatGPT",
                 reason_client_name: str = "DeepSeek",
                 chat_model: str = "gpt-3.5-turbo",
                 reason_model: str = "deepseek-ai/DeepSeek-R1",
                 ) -> None:
        self.wcf = wcf
        self.logger = LoggerConfig(__name__).get_logger()
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts()
        self._msg_timestamps = []
        # 导入配置
        self.config = config
        self.auto_send_interval = self.config.AUTO_SEND_INTERVAL or 10
        self.msg_id2msg_hist_index = {}

        # 记录上次在某个群说话时间
        self.last_group_chat_time = {}

        # 系统提示词
        self.system_prompt = config.CHARACTER_SYSTEM_PROMPT

        # 聊天模型
        self.chat_client = None
        self.chat_model = chat_model
        self.chat_messages = dict()
        if hasattr(llm_clients, chat_client_name):
            model_class = getattr(llm_clients, chat_client_name)
            proxy = config.PROXY if chat_client_name in config.MODELS_NEED_PROXY else None
            self.chat_client = model_class(api_key=config.CHAT_MODEL_API_KEY, base_url=config.CHAT_MODEL_BASE_URL, proxy=proxy)
            self.logger.info(f"已选择{chat_client_name}作为聊天模型")
        else:
            self.logger.warning(f"未定义{chat_client_name}模型")
        
        # 推理模型
        self.reason_client = None
        self.reason_model = reason_model
        model_class = getattr(llm_clients, reason_client_name)
        if model_class:
            proxy = config.PROXY if reason_client_name in config.MODELS_NEED_PROXY else None
            self.reason_client = model_class(api_key=config.REASON_MODEL_API_KEY, base_url=config.REASON_MODEL_BASE_URL, proxy=proxy)
            self.logger.info(f"已选择{reason_client_name}作为推理模型")
        else:
            self.logger.warning(f"未定义{reason_client_name}模型")
        
        self.storyteller = ImgStoryTeller() # v_model="OpenGVLab/InternVL2-26B"

    def updateMessage(self, wxid_or_roomid: str, message: str, role: str, nick_name: str = "佚名") -> None:
        now_time = str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if wxid_or_roomid not in self.chat_messages:
            self.chat_messages[wxid_or_roomid] = [
                {"role": "system", "content": self.system_prompt},
                {"role": "system", "content": f"消息中的时间戳仅供参考，和说话人一起都是系统自动生成的，你说话不要写这个开头。"}
            ]
        content = {"role": role, "content": f"[{now_time}] {nick_name}说：{message}"}
        self.chat_messages[wxid_or_roomid].append(content)
        
        # 返回消息的index
        return len(self.chat_messages[wxid_or_roomid]) - 1


    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False


    def toChengyu(self, msg: WxMsg) -> bool:
        """
        处理成语查询/接龙消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        status = False
        texts = re.findall(r"^([#?？])(.*)$", msg.content)
        # [('#', '天天向上')]
        if texts:
            flag = texts[0][0]
            text = texts[0][1]
            if flag == "#":  # 接龙
                if cy.isChengyu(text):
                    rsp = cy.getNext(text)
                    if rsp:
                        self.sendTextMsg(rsp, msg.roomid)
                        status = True
            elif flag in ["?", "？"]:  # 查词
                if cy.isChengyu(text):
                    rsp = cy.getMeaning(text)
                    if rsp:
                        self.sendTextMsg(rsp, msg.roomid)
                        status = True

        return status
        
    def processMsg(self, msg: WxMsg) -> None:
        """当接收到消息的时候，会调用本方法。如果不实现本方法，则打印原始消息。
        此处可进行自定义发送的内容,如通过 msg.content 关键字自动获取当前天气信息，并发送到对应的群组@发送者
        群号：msg.roomid  微信ID：msg.sender  消息内容：msg.content
        content = "xx天气信息为："
        receivers = msg.roomid
        self.sendTextMsg(content, receivers, msg.sender)
        """
        print(f"收到新消息 - 类型: {msg.type}, 发送者: {msg.sender}, 内容: {msg.content}")
        
        ## 群聊和私聊的回复逻辑有区别：
        # 1. 群聊消息：回复@，以及每隔一段时间，在群里闲聊一句活跃气氛
        # 2. 私聊消息：回复每一条消息
        msg_from = msg.roomid if msg.from_group() else msg.sender
        sender_nick_name = self.allContacts[msg.sender] if not msg.from_group() else self.wcf.get_alias_in_chatroom(msg.sender, msg.roomid)
        my_nick_name = self.allContacts[self.wxid] if not msg.from_group() else self.wcf.get_alias_in_chatroom(self.wxid, msg_from)
        
        print(f"消息来源: {msg_from}, 发送者昵称: {sender_nick_name}, 我的昵称: {my_nick_name}")

        # 如果消息是引用消息
        if msg.type == 49:
            parse_xml_res = parse_xml_msg(msg.content)
            txt_content = parse_xml_res["title"]
            ref_msg = parse_xml_res["refermsg"]
            print(f"解析引用消息 - 标题: {txt_content}, 引用内容: {ref_msg}")
        else:
            txt_content = msg.content

        # 记录必要的消息到记忆列表
        def append_to_msg_hist_and_index(msg: WxMsg):
            if msg.id in self.msg_id2msg_hist_index:
                return
            
            if msg.type == 0x01:
                msg_to_append = txt_content
            elif msg.type == 3: # 和视频?
                msg_to_append = f"media_url:{msg.extra}"
            elif msg.type == 49: # 如果消息是引用消息   
                # 引用视频
                # 引用语音
                # 引用文件
                # 引用链接

                has_index = False
                ref_msg_content = ref_msg["content"] # xml中的content，多媒体为未知编码，所以从记录的索引找
                if ref_msg["type"] == 3: # 多媒体，访问hist列表里对应的索引
                    msg_idx_tp = self.msg_id2msg_hist_index.get(ref_msg["svrid"], None)
                    if msg_idx_tp:
                        has_index = True
                        ref_msg_from, ref_msg_idx = msg_idx_tp
                        ref_msg_in_hist = self.chat_messages[ref_msg_from][ref_msg_idx]
                        ref_msg_content = ref_msg_in_hist["content"]                    

                print("内容：", txt_content)
                print("引用消息：", ref_msg)
                # 如果有@且记录过索引，则下载指定图片并替换链接为解析描述
                if ref_msg["type"] == 3 and mentions(msg, config.CHARACTER_NAMES + [my_nick_name]) \
                    and has_index and "media_url:" in ref_msg_content:  # "media_url:" in 说明还没下载和替换成img desc
                    ref_img_extra = ref_msg_content.split("media_url:")[1]
                    time_name = ref_msg_content.split("：")[0]
                    sv_dir = "/".join(ref_img_extra.split("/")[:-1])
                    ref_img_sv_path = self.wcf.download_image(ref_msg["svrid"], ref_img_extra, sv_dir)
                    self.logger.info(f"下载引用消息图片成功：{ref_img_sv_path}")
                    ref_msg_content = self.storyteller.parse_img_to_des(ref_img_sv_path)
                    ref_msg_content = f"{time_name}：{ref_msg_content}"
                msg_to_append = f"{txt_content}\n[这条信息引用了msg id -> {ref_msg['svrid']}, 内容为：{ref_msg_content}]"
                if has_index:
                    ref_msg_content = f"msg id -> {ref_msg['svrid']} {ref_msg_content}" # 用msg id做好引用标记
                    self.chat_messages[msg_from][ref_msg_idx]["content"] = ref_msg_content
            else: # 其他类型消息，不记忆
                return
            idx = self.updateMessage(msg_from, msg_to_append, "user", sender_nick_name)
            self.msg_id2msg_hist_index[msg.id] = (msg_from, idx) # 存下索引
        

        need_to_reply = False
        # 需要响应的群聊
        if msg.from_group() and msg.roomid in self.config.ENABLED_GROUPS:  # 使用self.config
            print(f"-------------- debug 响应群聊新消息 ----------------")
            # 记录群消息到记忆列表
            append_to_msg_hist_and_index(msg)

            # 每超过N分钟，在群里闲聊一句活跃气氛
            time_last_group_chat = self.last_group_chat_time.get(msg.roomid, time.time())
            time_now = time.time()
            time_interval = time_now - time_last_group_chat
            self.logger.info(f"群聊消息间隔：{time_interval}秒")
            if time_interval > self.auto_send_interval * 60 or mentions(msg, config.CHARACTER_NAMES + [my_nick_name]):
                need_to_reply = True
                self.last_group_chat_time[msg.roomid] = time_now
                
        # 处理非群聊
        elif not msg.from_group():
            print(f"-------------- debug 响应非群聊新消息 ----------------")
            if msg.type == 37:  # 好友请求
                self.autoAcceptFriendRequest(msg)
            elif msg.type == 10000:  # 系统信息
                self.sayHiToNewFriend(msg)
            elif msg.from_self() and msg.content == "^更新配置$":
                self.config.reload()
                self.logger.info("配置已更新")
            else: # 其他私聊消息
                append_to_msg_hist_and_index(msg)
                need_to_reply = True
                if reply_txt:
                    self.updateMessage(msg_from, reply_txt, "assistant", my_nick_name)

        # 生成回复内容
        if need_to_reply:
            # 存在以下关键词，升级prompt
            if re.search("(打分|打个分|点评|锐评)", txt_content):
                score_prompt = self.config.IMG_TELL_USER_PROMPT
                ori_content = self.chat_messages[msg_from][-1]["content"]
                self.chat_messages[msg_from][-1]["content"] = score_prompt.format(img_des=ori_content)
                
            # 如果存在以下关键词，用推理模型
            reasoning = False
            reply_txt = ""
            for word in {"打分", "打个分", "点评", "锐评", "仔细想想", "推理"}:
                if word in txt_content:
                    reasoning = True
                    break
            if reasoning: # 用推理模型
                print("--------------使用推理模型-------------")
                chunk_gen = self.reason_client.chat(self.chat_messages[msg_from], model=self.reason_model, stream=True)
                print("思考中：")
                reasoning_finished = False
                for chunk in chunk_gen:
                    if chunk.choices[0].delta.reasoning_content:
                        print(chunk.choices[0].delta.reasoning_content, end="", flush=True)
                    if chunk.choices[0].delta.content:
                        if not reasoning_finished:
                            reasoning_finished = True
                            print("\n正式回答：")
                        print(chunk.choices[0].delta.content, end="", flush=True)
                        reply_txt += chunk.choices[0].delta.content

            else: # 其他情况，用普通chat模型
                print("----------------使用普通聊天模型--------------------")
                chat_response = self.chat_client.chat(self.chat_messages[msg_from], model=self.chat_model, stream=True)
                for chunk in chat_response:
                    if chunk.choices[0].delta.content:
                        print(chunk.choices[0].delta.content, end="", flush=True)
                        reply_txt += chunk.choices[0].delta.content
            
            # rm time and nick_name
            reply_txt = re.sub(r"\[.*?\] .*?说：", "", reply_txt)

            # 如果有效回复生成
            if reply_txt:
                print(f"生成回复成功 - 回复内容: {reply_txt}")
                # 只有群聊被@了，才需要@
                at_list = msg.sender if msg.from_group() and mentions(msg, my_nick_name) else ""
                
                # 发送
                self.sendTextMsg(reply_txt, msg_from, at_list)

                # 更新消息
                self.updateMessage(msg_from, reply_txt, "assistant", my_nick_name)
            else:
                self.logger.error(f"无法从LLM获得回复...")
            
    def onMsg(self, msg: WxMsg) -> int:
        try:
            self.processMsg(msg)
        except Exception as e:
            self.logger.error(e)

        return 0

    def enableRecvMsg(self) -> None:
        self.wcf.enable_recv_msg(self.onMsg)

    def enableReceivingMsg(self) -> None:
        def innerProcessMsg(wcf: Wcf):
            while wcf.is_receiving_msg():
                try:
                    msg = wcf.get_msg()
                    self.logger.info(msg)
                    self.processMsg(msg)
                except Empty:
                    continue
                except Exception as e:
                    self.logger.error(f"Receiving message error: {e}")

        self.wcf.enable_receiving_msg()
        Thread(target=innerProcessMsg, name="GetMessage", args=(self.wcf,), daemon=True).start()

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "") -> None:
        """ 发送消息
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        """
        # 随机延迟0.3-1.3秒，并且一分钟内发送限制
        time.sleep(float(str(time.time()).split('.')[-1][-2:]) / 100.0 + 0.3)
        now = time.time()
        if self.config.SEND_RATE_LIMIT > 0:
            # 清除超过1分钟的记录
            self._msg_timestamps = [t for t in self._msg_timestamps if now - t < 60]
            if len(self._msg_timestamps) >= self.config.SEND_RATE_LIMIT:
                self.logger.warning("发送消息过快，已达到每分钟"+self.config.SEND_RATE_LIMIT+"条上限。")
                return
            self._msg_timestamps.append(now)

        # msg 中需要有 @ 名单中一样数量的 @
        ats = ""
        if at_list:
            if at_list == "notify@all":  # @所有人
                ats = " @所有人"
            else:
                wxids = at_list.split(",")
                for wxid in wxids:
                    # 根据 wxid 查找群昵称
                    ats += f" @{self.wcf.get_alias_in_chatroom(wxid, receiver)}"

        # {msg}{ats} 表示要发送的消息内容后面紧跟@，例如 北京天气情况为：xxx @张三
        msg = msg.strip()
        if ats == "":
            self.logger.info(f"To {receiver}: {msg}")
            self.wcf.send_text(f"{msg}", receiver, at_list)
        else:
            self.logger.info(f"To {receiver}: {ats} {msg}")
            self.wcf.send_text(f"{ats} {msg}", receiver, at_list)

    def getAllContacts(self) -> dict:
        """
        获取联系人（包括好友、公众号、服务号、群成员……）
        格式: {"wxid": "NickName"}
        """
        contacts = self.wcf.query_sql("MicroMsg.db", "SELECT UserName, NickName FROM Contact;")
        return {contact["UserName"]: contact["NickName"] for contact in contacts}

    def keepRunningAndBlockProcess(self) -> None:
        """
        保持机器人运行，不让进程退出
        """
        while True:
            self.runPendingJobs()
            time.sleep(1)

    def autoAcceptFriendRequest(self, msg: WxMsg) -> None:
        try:
            xml = ET.fromstring(msg.content)
            v3 = xml.attrib["encryptusername"]
            v4 = xml.attrib["ticket"]
            scene = int(xml.attrib["scene"])
            self.wcf.accept_new_friend(v3, v4, scene)

        except Exception as e:
            self.logger.error(f"同意好友出错：{e}")

    def sayHiToNewFriend(self, msg: WxMsg) -> None:
        nickName = re.findall(r"你已添加了(.*)，现在可以开始聊天了。", msg.content)
        if nickName:
            # 添加了好友，更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            self.sendTextMsg(f"Hi {nickName[0]}，我自动通过了你的好友请求。", msg.sender)

    def newsReport(self) -> None:
        receivers = self.config.NEWS_RECEIVERS  # 使用self.config
        if not receivers:
            return

        news = News().get_important_news()
        for r in receivers:
            self.sendTextMsg(news, r)

    def weatherReport(self) -> None:
        receivers = self.config.WEATHER_CONFIG["receivers"]  # 使用self.config
        city_code = self.config.WEATHER_CONFIG["city_code"]
        if not receivers or not city_code:
            self.logger.warning("未配置天气城市代码或接收人")
            return

        report = Weather(city_code).get_weather()
        for r in receivers:
            self.sendTextMsg(report, r)
